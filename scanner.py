import hashlib
from datetime import datetime, timezone
from pathlib import Path


def calculate_sha256(file_path: Path):
    hasher = hashlib.sha256()

    with file_path.open("rb") as file:
        chunk = file.read(65536)

        while chunk:
            hasher.update(chunk)
            chunk = file.read(65536)

    return hasher.hexdigest()


def scan_directory(directory_path: Path):
    entries = []

    for file_path in directory_path.rglob("*"):
        try:
            if not file_path.is_file() or file_path.is_symlink():
                continue

            file_stat = file_path.stat()
            file_hash = calculate_sha256(file_path)

        except OSError:
            continue

        entries.append({
            "relative_path": str(file_path.relative_to(directory_path)),
            "size_bytes": file_stat.st_size,
            "modified_at": datetime.fromtimestamp(
                file_stat.st_mtime,
                tz=timezone.utc
            ).isoformat(),
            "sha256": file_hash,
        })

    return entries