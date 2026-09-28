from pathlib import Path
import sqlite3

import csv
import json
from io import StringIO

from flask import Flask,  Response, flash, redirect, render_template, request, url_for
from database import get_connection, init_db
from datetime import datetime, timezone

from scanner import scan_directory

from comparison import compare_latest_snapshots, compare_snapshots

app = Flask(__name__)


@app.template_filter("localtime")
def localtime(value):
    parsed = datetime.fromisoformat(value)

    # 기존 SQLite 기록은 UTC 시간인데 시간대 정보가 없으므로 UTC로 해석
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")



app.config["SECRET_KEY"] = "local-development-key"

init_db()


@app.route("/")
def index():
    connection = get_connection()
    directories = connection.execute("""
        SELECT id, path, label, created_at
        FROM watched_directories
        ORDER BY created_at DESC
    """).fetchall()
    connection.close()

    return render_template("index.html", directories=directories)


@app.route("/directories", methods=["POST"])
def add_directory():
    raw_path = request.form.get("path", "").strip()
    label = request.form.get("label", "").strip()

    if not raw_path:
        flash("Please enter a directory path.", "error")
        return redirect(url_for("index"))

    directory_path = Path(raw_path).expanduser()

    if not directory_path.is_dir():
        flash("That path does not exist or is not a directory.", "error")
        return redirect(url_for("index"))

    resolved_path = str(directory_path.resolve())

    try:
        connection = get_connection()
        connection.execute(
            "INSERT INTO watched_directories (path, label) VALUES (?, ?)",
            (resolved_path, label or None)
        )
        connection.commit()
        connection.close()
        flash("Directory registered.", "success")

    except sqlite3.IntegrityError:
        flash("This directory is already registered.", "error")

    return redirect(url_for("index"))


@app.route("/directories/<int:directory_id>/scan", methods=["POST"])
def scan_registered_directory(directory_id):
    connection = get_connection()

    directory = connection.execute(
        "SELECT id, path FROM watched_directories WHERE id = ?",
        (directory_id,)
    ).fetchone()

    if directory is None:
        connection.close()
        flash("Directory not found.", "error")
        return redirect(url_for("index"))

    try:
        entries = scan_directory(Path(directory["path"]))

    except OSError:
        connection.close()
        flash("The directory could not be scanned.", "error")
        return redirect(url_for("index"))

    total_size = sum(entry["size_bytes"] for entry in entries)

    scanned_at = datetime.now().astimezone().isoformat(timespec="seconds")

    cursor = connection.execute(
        """
        INSERT INTO snapshots (directory_id, scanned_at, file_count, total_size_bytes)
        VALUES (?, ?, ?, ?)
        """,
        (directory_id, scanned_at, len(entries), total_size),
    )

    snapshot_id = cursor.lastrowid

    connection.executemany("""
        INSERT INTO file_entries
            (snapshot_id, relative_path, size_bytes, modified_at, sha256)
        VALUES (?, ?, ?, ?, ?)
    """, [
        (
            snapshot_id,
            entry["relative_path"],
            entry["size_bytes"],
            entry["modified_at"],
            entry["sha256"]
        )
        for entry in entries
    ])

    connection.commit()
    connection.close()

    flash(f"Snapshot saved: {len(entries)} files scanned.", "success")
    return redirect(url_for("index"))


@app.route("/directories/<int:directory_id>/changes")
def view_changes(directory_id):
    connection = get_connection()

    directory = connection.execute("""
        SELECT id, path, label
        FROM watched_directories
        WHERE id = ?
    """, (directory_id,)).fetchone()

    connection.close()

    if directory is None:
        flash("Directory not found.", "error")
        return redirect(url_for("index"))

    comparison = compare_latest_snapshots(directory_id)

    if comparison is None:
        flash("At least two snapshots are required for comparison.", "error")
        return redirect(url_for("index"))

    return render_template(
        "changes.html",
        directory=directory,
        comparison=comparison,
        comparison_title="Latest changes",
        comparison_description="Changes detected between the two most recent snapshots."
    )


@app.route("/directories/<int:directory_id>/history")
def view_history(directory_id):
    connection = get_connection()

    directory = connection.execute("""
        SELECT id, path, label
        FROM watched_directories
        WHERE id = ?
    """, (directory_id,)).fetchone()

    snapshots = connection.execute("""
        SELECT id, scanned_at, file_count, total_size_bytes
        FROM snapshots
        WHERE directory_id = ?
        ORDER BY id ASC
    """, (directory_id,)).fetchall()

    connection.close()

    if directory is None:
        flash("Directory not found.", "error")
        return redirect(url_for("index"))

    history = []
    previous = None

    for snapshot in snapshots:
        item = dict(snapshot)
        item["previous_snapshot_id"] = (
            previous["id"] if previous is not None else None
        )

        if previous is None:
            item["file_count_change"] = None
            item["size_change"] = None
        else:
            item["file_count_change"] = (
                item["file_count"] - previous["file_count"]
            )
            item["size_change"] = (
                item["total_size_bytes"] - previous["total_size_bytes"]
            )

        history.append(item)
        previous = item

    history.reverse()

    return render_template(
        "history.html",
        directory=directory,
        history=history
    )


@app.route("/directories/<int:directory_id>/delete", methods=["POST"])
def delete_directory(directory_id):
    connection = get_connection()

    cursor = connection.execute(
        "DELETE FROM watched_directories WHERE id = ?",
        (directory_id,)
    )

    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        flash("Directory not found.", "error")
    else:
        flash("Directory and its snapshot history were removed.", "success")

    return redirect(url_for("index"))


def get_full_history(directory_id):
    connection = get_connection()

    directory = connection.execute("""
        SELECT id, path, label
        FROM watched_directories
        WHERE id = ?
    """, (directory_id,)).fetchone()

    snapshots = connection.execute("""
        SELECT id, scanned_at, file_count, total_size_bytes
        FROM snapshots
        WHERE directory_id = ?
        ORDER BY id ASC
    """, (directory_id,)).fetchall()

    connection.close()

    if directory is None:
        return None, [], []

    scan_history = [dict(snapshot) for snapshot in snapshots]
    change_history = []

    for previous, latest in zip(snapshots, snapshots[1:]):
        changes = compare_snapshots(previous["id"], latest["id"])

        for change in changes:
            change_history.append({
                "from_snapshot_id": previous["id"],
                "from_scanned_at": previous["scanned_at"],
                "to_snapshot_id": latest["id"],
                "to_scanned_at": latest["scanned_at"],
                "status": change["status"],
                "old_path": change.get("old_path", ""),
                "path": change["path"],
                "size_bytes": change["size_bytes"]
            })

    return dict(directory), scan_history, change_history


def get_range_events(directory_id, start_snapshot_id, end_snapshot_id):
    connection = get_connection()

    snapshots = connection.execute(
        """
        SELECT id, scanned_at
        FROM snapshots
        WHERE directory_id = ?
          AND id >= ?
          AND id <= ?
        ORDER BY id ASC
        """,
        (directory_id, start_snapshot_id, end_snapshot_id),
    ).fetchall()

    connection.close()

    events = []

    for previous_snapshot, latest_snapshot in zip(snapshots, snapshots[1:]):
        changes = compare_snapshots(
            previous_snapshot["id"],
            latest_snapshot["id"],
        )

        for change in changes:
            event = dict(change)
            event["from_scanned_at"] = previous_snapshot["scanned_at"]
            event["to_scanned_at"] = latest_snapshot["scanned_at"]
            events.append(event)

    return events




@app.route("/directories/<int:directory_id>/scan-history.csv")
def export_scan_history_csv(directory_id):
    directory, scan_history, _ = get_full_history(directory_id)

    if directory is None:
        flash("Directory not found.", "error")
        return redirect(url_for("index"))

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "snapshot_id",
        "scanned_at",
        "file_count",
        "total_size_bytes"
    ])

    for snapshot in scan_history:
        writer.writerow([
            snapshot["id"],
            snapshot["scanned_at"],
            snapshot["file_count"],
            snapshot["total_size_bytes"]
        ])

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=scan-history.csv"
        }
    )


@app.route("/directories/<int:directory_id>/change-history.csv")
def export_change_history_csv(directory_id):
    directory, _, change_history = get_full_history(directory_id)

    if directory is None:
        flash("Directory not found.", "error")
        return redirect(url_for("index"))

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "from_scanned_at",
        "to_scanned_at",
        "status",
        "old_path",
        "path",
        "size_bytes"
    ])

    for change in change_history:
        writer.writerow([
            change["from_scanned_at"],
            change["to_scanned_at"],
            change["status"],
            change["old_path"],
            change["path"],
            change["size_bytes"]
        ])

    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=change-history.csv"
        }
    )


@app.route("/directories/<int:directory_id>/history.json")
def export_full_history_json(directory_id):
    directory, scan_history, change_history = get_full_history(directory_id)

    if directory is None:
        flash("Directory not found.", "error")
        return redirect(url_for("index"))

    export_data = {
        "directory": directory,
        "scan_history": scan_history,
        "change_history": change_history
    }

    return Response(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment; filename=file-history.json"
        }
    )



@app.route(
    "/directories/<int:directory_id>/compare/"
    "<int:previous_snapshot_id>/<int:latest_snapshot_id>"
)
def view_historical_comparison(
    directory_id,
    previous_snapshot_id,
    latest_snapshot_id
):
    connection = get_connection()

    directory = connection.execute("""
        SELECT id, path, label
        FROM watched_directories
        WHERE id = ?
    """, (directory_id,)).fetchone()

    previous_snapshot = connection.execute("""
        SELECT id, scanned_at
        FROM snapshots
        WHERE id = ? AND directory_id = ?
    """, (previous_snapshot_id, directory_id)).fetchone()

    latest_snapshot = connection.execute("""
        SELECT id, scanned_at
        FROM snapshots
        WHERE id = ? AND directory_id = ?
    """, (latest_snapshot_id, directory_id)).fetchone()

    connection.close()

    if (
        directory is None
        or previous_snapshot is None
        or latest_snapshot is None
        or previous_snapshot["id"] >= latest_snapshot["id"]
    ):
        flash("Invalid snapshot comparison.", "error")
        return redirect(url_for("view_history", directory_id=directory_id))

    comparison = {
        "previous_snapshot": dict(previous_snapshot),
        "latest_snapshot": dict(latest_snapshot),
        "changes": compare_snapshots(
            previous_snapshot_id,
            latest_snapshot_id
        )
    }

    return render_template(
        "changes.html",
        directory=directory,
        comparison=comparison,
        comparison_title="Historical comparison",
        comparison_description=(
            "Changes detected between the selected consecutive snapshots."
        )
    )

@app.route("/directories/<int:directory_id>/compare")
def select_snapshot_comparison(directory_id):
    previous_snapshot_id = request.args.get(
        "previous_snapshot_id",
        type=int
    )
    latest_snapshot_id = request.args.get(
        "latest_snapshot_id",
        type=int
    )

    if previous_snapshot_id is None or latest_snapshot_id is None:
        flash("Please select two snapshots.", "error")
        return redirect(url_for("view_history", directory_id=directory_id))

    mode = request.args.get("mode", "comparison")

    if mode == "events":
        return redirect(
            url_for(
                "view_range_events",
                directory_id=directory_id,
                previous_snapshot_id=previous_snapshot_id,
                latest_snapshot_id=latest_snapshot_id,
            )
        )

    return redirect(
        url_for(
            "view_historical_comparison",
            directory_id=directory_id,
            previous_snapshot_id=previous_snapshot_id,
            latest_snapshot_id=latest_snapshot_id,
        )
    )


@app.route("/directories/<int:directory_id>/events")
def view_range_events(directory_id):
    start_snapshot_id = request.args.get("previous_snapshot_id", type=int)
    end_snapshot_id = request.args.get("latest_snapshot_id", type=int)

    if start_snapshot_id is None or end_snapshot_id is None:
        flash("Please select two snapshots.", "error")
        return redirect(url_for("view_history", directory_id=directory_id))

    if start_snapshot_id >= end_snapshot_id:
        flash("Select an earlier snapshot first, then a later snapshot.", "error")
        return redirect(url_for("view_history", directory_id=directory_id))

    connection = get_connection()

    directory = connection.execute(
        "SELECT * FROM watched_directories WHERE id = ?",
        (directory_id,),
    ).fetchone()

    start_snapshot = connection.execute(
        """
        SELECT * FROM snapshots
        WHERE id = ? AND directory_id = ?
        """,
        (start_snapshot_id, directory_id),
    ).fetchone()

    end_snapshot = connection.execute(
        """
        SELECT * FROM snapshots
        WHERE id = ? AND directory_id = ?
        """,
        (end_snapshot_id, directory_id),
    ).fetchone()

    connection.close()

    if directory is None or start_snapshot is None or end_snapshot is None:
        flash("That snapshot selection is not valid.", "error")
        return redirect(url_for("index"))

    events = get_range_events(
        directory_id,
        start_snapshot_id,
        end_snapshot_id,
    )

    return render_template(
        "events.html",
        directory=directory,
        start_snapshot=start_snapshot,
        end_snapshot=end_snapshot,
        events=events,
    )




if __name__ == "__main__":
    app.run(debug=True)