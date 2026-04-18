from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        tmp_path = Path(handle.name)
    os.replace(tmp_path, path)


def read_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    ensure_directory(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sha256_text(parts: list[str | None]) -> str:
    canonical = "|".join("" if part is None else part for part in parts)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def mask_identifier(value: str | None, prefix: int = 4, suffix: int = 2) -> str | None:
    if value is None:
        return None
    if len(value) <= prefix + suffix:
        return "*" * len(value)
    stars = "*" * (len(value) - prefix - suffix)
    return f"{value[:prefix]}{stars}{value[-suffix:]}"


def parse_date(value: str) -> date:
    return date.fromisoformat(value)

