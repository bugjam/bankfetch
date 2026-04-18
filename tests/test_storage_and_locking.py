from __future__ import annotations

from pathlib import Path

import pytest

from bankfetch.errors import LockContentionError
from bankfetch.locking import FileLock
from bankfetch.models import ActiveSession, BankIdentity, Checkpoints, SessionMetadata
from bankfetch.session_store import SessionStore


def test_session_store_round_trips_session_and_checkpoints(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "state", tmp_path / "out")
    session = ActiveSession(
        bank=BankIdentity(aspsp_id="bank-1", display_name="Nordea", country_code="DK"),
        session=SessionMetadata(session_id="sess-1", status="AUTHORIZED"),
        accounts=[],
    )
    checkpoints = Checkpoints()
    store.save_active_session(session)
    store.save_checkpoints(checkpoints)
    assert store.load_active_session().session.session_id == "sess-1"
    assert store.load_checkpoints().version == 1


def test_lock_contention_raises(tmp_path: Path) -> None:
    lock_dir = tmp_path / "state" / "lock"
    with FileLock(lock_dir):
        with pytest.raises(LockContentionError):
            with FileLock(lock_dir):
                pass
