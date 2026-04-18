from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ActiveSession, AuthInitState, Checkpoints
from .utils import append_jsonl, ensure_directory, read_json_file, read_jsonl, sanitize_filename, write_json_atomic


class SessionStore:
    def __init__(self, state_dir: Path, output_dir: Path, session_alias: str = "default"):
        self.state_dir = ensure_directory(state_dir)
        self.output_dir = ensure_directory(output_dir)
        self.session_alias = sanitize_filename(session_alias)

    @property
    def state_prefix(self) -> str:
        if self.session_alias == "default":
            return ""
        return f"_{self.session_alias}"

    @property
    def output_prefix(self) -> str:
        if self.session_alias == "default":
            return ""
        return f"{self.session_alias}__"

    @property
    def active_session_path(self) -> Path:
        return self.state_dir / f"active_session{self.state_prefix}.json"

    @property
    def auth_init_path(self) -> Path:
        return self.state_dir / f"auth_init{self.state_prefix}.json"

    @property
    def checkpoints_path(self) -> Path:
        return self.state_dir / f"checkpoints{self.state_prefix}.json"

    @property
    def lock_dir(self) -> Path:
        return self.state_dir / "lock"

    def save_auth_init(self, auth_init: AuthInitState) -> None:
        write_json_atomic(self.auth_init_path, auth_init.model_dump(mode="json"))

    def load_auth_init(self) -> AuthInitState:
        return AuthInitState.model_validate(read_json_file(self.auth_init_path))

    def save_active_session(self, session: ActiveSession) -> None:
        write_json_atomic(self.active_session_path, session.model_dump(mode="json"))

    def load_active_session(self) -> ActiveSession:
        return ActiveSession.model_validate(read_json_file(self.active_session_path))

    def save_checkpoints(self, checkpoints: Checkpoints) -> None:
        write_json_atomic(self.checkpoints_path, checkpoints.model_dump(mode="json"))

    def load_checkpoints(self) -> Checkpoints:
        if not self.checkpoints_path.exists():
            return Checkpoints()
        return Checkpoints.model_validate(read_json_file(self.checkpoints_path))

    def archive_raw(
        self,
        category: str,
        account_key: str,
        fetch_time: datetime,
        payload: dict[str, Any],
        *,
        page_number: int | None = None,
    ) -> Path:
        date_path = Path(fetch_time.strftime("%Y")) / fetch_time.strftime("%m") / fetch_time.strftime("%d")
        account_path = sanitize_filename(account_key)
        filename = fetch_time.strftime("%Y%m%dT%H%M%SZ")
        if page_number is not None:
            filename = f"{filename}_page_{page_number}"
        path = self.output_dir / "raw" / category / date_path / account_path / f"{filename}.json"
        ensure_directory(path.parent)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def append_normalized(self, category: str, account_key: str, records: list[dict[str, Any]]) -> Path:
        path = self.output_dir / "normalized" / category / f"{self.output_prefix}{sanitize_filename(account_key)}.jsonl"
        append_jsonl(path, records)
        return path

    def write_latest_transactions(self, account_key: str, records: list[dict[str, Any]]) -> Path:
        path = (
            self.output_dir
            / "normalized"
            / "transactions"
            / f"{self.output_prefix}{sanitize_filename(account_key)}_latest.jsonl"
        )
        ensure_directory(path.parent)
        path.write_text("", encoding="utf-8")
        append_jsonl(path, records)
        return path

    def read_latest_transactions(self, account_key: str) -> list[dict[str, Any]]:
        path = (
            self.output_dir
            / "normalized"
            / "transactions"
            / f"{self.output_prefix}{sanitize_filename(account_key)}_latest.jsonl"
        )
        return read_jsonl(path)
