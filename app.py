from pathlib import Path
import sqlite3

from flask import Flask, flash, redirect, render_template, request, url_for
from database import get_connection, init_db

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


if __name__ == "__main__":
    app.run(debug=True)