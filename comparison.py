from database import get_connection


def file_has_changed(previous, latest):
    if previous["sha256"] and latest["sha256"]:
        return previous["sha256"] != latest["sha256"]

    return (
        previous["size_bytes"] != latest["size_bytes"]
        or previous["modified_at"] != latest["modified_at"]
    )

def compare_latest_snapshots(directory_id):
    connection = get_connection()

    snapshots = connection.execute("""
        SELECT id, scanned_at
        FROM snapshots
        WHERE directory_id = ?
        ORDER BY id DESC
        LIMIT 2
    """, (directory_id,)).fetchall()

    if len(snapshots) < 2:
        connection.close()
        return None

    latest_snapshot = snapshots[0]
    previous_snapshot = snapshots[1]

    previous_entries = {
        row["relative_path"]: dict(row)
        for row in connection.execute("""
            SELECT relative_path, size_bytes, modified_at, sha256
            FROM file_entries
            WHERE snapshot_id = ?
        """, (previous_snapshot["id"],)).fetchall()
    }

    latest_entries = {
        row["relative_path"]: dict(row)
        for row in connection.execute("""
            SELECT relative_path, size_bytes, modified_at, sha256
            FROM file_entries
            WHERE snapshot_id = ?
        """, (latest_snapshot["id"],)).fetchall()
    }

    connection.close()


    added = []
    deleted = []
    modified = []

    for path in sorted(previous_entries.keys() | latest_entries.keys()):
        previous = previous_entries.get(path)
        latest = latest_entries.get(path)

        if previous is None:
            added.append({
                "status": "Added",
                "path": path,
                "size_bytes": latest["size_bytes"],
                "sha256": latest["sha256"]
            })

        elif latest is None:
            deleted.append({
                "status": "Deleted",
                "path": path,
                "size_bytes": previous["size_bytes"],
                "sha256": previous["sha256"]
            })

        elif file_has_changed(previous, latest):
            modified.append({
                "status": "Modified",
                "path": path,
                "size_bytes": latest["size_bytes"]
            })

    added_by_hash = {}
    deleted_by_hash = {}

    for change in added:
        if change["sha256"]:
            added_by_hash.setdefault(change["sha256"], []).append(change)

    for change in deleted:
        if change["sha256"]:
            deleted_by_hash.setdefault(change["sha256"], []).append(change)

    renamed = []
    renamed_added_paths = set()
    renamed_deleted_paths = set()

    matching_hashes = set(added_by_hash) & set(deleted_by_hash)

    for file_hash in matching_hashes:
        for deleted_file, added_file in zip(
            deleted_by_hash[file_hash],
            added_by_hash[file_hash]
        ):
            renamed.append({
                "status": "Renamed",
                "old_path": deleted_file["path"],
                "path": added_file["path"],
                "size_bytes": added_file["size_bytes"]
            })

            renamed_added_paths.add(added_file["path"])
            renamed_deleted_paths.add(deleted_file["path"])

    changes = (
        renamed
        + [change for change in added if change["path"] not in renamed_added_paths]
        + [change for change in deleted if change["path"] not in renamed_deleted_paths]
        + modified
    )

    changes.sort(key=lambda change: change["path"])

    
    return {
        "previous_snapshot": dict(previous_snapshot),
        "latest_snapshot": dict(latest_snapshot),
        "changes": changes
    }