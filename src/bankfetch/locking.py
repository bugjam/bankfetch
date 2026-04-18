from __future__ import annotations

import os
from pathlib import Path

from .errors import LockContentionError
from .utils import ensure_directory, iso_now, write_json_atomic


class FileLock:
    def __init__(self, lock_dir: Path):
        self.lock_dir = lock_dir
        self.lock_file = lock_dir / "sync.lock"

    def __enter__(self) -> "FileLock":
        ensure_directory(self.lock_dir)
        try:
            fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LockContentionError(f"lock already held: {self.lock_file}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f'{{"created_at":"{iso_now()}","pid":{os.getpid()}}}\n')
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        try:
            self.lock_file.unlink(missing_ok=True)
        except OSError:
            pass

