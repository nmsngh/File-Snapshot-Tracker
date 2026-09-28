from pathlib import Path
import sqlite3

from flask import Flask, flash, redirect, render_template, request, url_for
from database import get_connection, init_db

from scanner import scan_directory

app = Flask(__name__)
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

    cursor = connection.execute("""
        INSERT INTO snapshots (directory_id, file_count, total_size_bytes)
        VALUES (?, ?, ?)
    """, (directory_id, len(entries), total_size))

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
            None
        )
        for entry in entries
    ])

    connection.commit()
    connection.close()

    flash(f"Snapshot saved: {len(entries)} files scanned.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)