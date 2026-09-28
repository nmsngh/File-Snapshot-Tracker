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

    changes = []

    for path in sorted(previous_entries.keys() | latest_entries.keys()):
        previous = previous_entries.get(path)
        latest = latest_entries.get(path)

        if previous is None:
            changes.append({
                "status": "Added",
                "path": path,
                "size_bytes": latest["size_bytes"]
            })

        elif latest is None:
            changes.append({
                "status": "Deleted",
                "path": path,
                "size_bytes": previous["size_bytes"]
            })

        elif file_has_changed(previous, latest):
            changes.append({
                "status": "Modified",
                "path": path,
                "size_bytes": latest["size_bytes"]
            })

    return {
        "previous_snapshot": dict(previous_snapshot),
        "latest_snapshot": dict(latest_snapshot),
        "changes": changes
    }