from datetime import datetime, timezone
from pathlib import Path


def scan_directory(directory_path: Path):
    entries = []


    for file_path in directory_path.rglob("*"):
        try:
            if not file_path.is_file() or file_path.is_symlink():
                continue

            file_stat = file_path.stat()

        except OSError:
            continue

        entries.append({
            "relative_path": str(file_path.relative_to(directory_path)),
            "size_bytes": file_stat.st_size,
            "modified_at": datetime.fromtimestamp(
                file_stat.st_mtime,
                tz=timezone.utc
            ).isoformat(),
        })

    return entries