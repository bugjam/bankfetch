from __future__ import annotations

from datetime import date
from uuid import uuid4

from .auth import build_jwt
from .balances import normalize_balances
from .enable_client import enable_client
from .errors import PartialSyncError, ReauthorizationRequiredError, SessionInvalidError
from .locking import FileLock
from .logging import get_logger
from .models import AccountState, Checkpoints, SyncSummary
from .session_store import SessionStore
from .transactions import dedupe_transactions, derive_fetch_window, normalize_transactions_page, update_checkpoint_from_records
from .utils import iso_now, utc_now


def ensure_session_usable(session_status: str) -> None:
    usable = {"AUTHORIZED", "ACTIVE"}
    if session_status in usable:
        return
    if session_status in {"EXPIRED", "REVOKED"}:
        raise ReauthorizationRequiredError(f"session requires reauthorization: {session_status}")
    raise SessionInvalidError(f"session is not usable: {session_status}")


def run_sync(
    config,
    *,
    session_aliases: list[str],
    all_accounts: bool,
    fail_fast: bool,
    dry_run: bool,
    selected_accounts: list[str] | None = None,
) -> SyncSummary:
    logger = get_logger()
    lock_store = SessionStore(config.sync.state_dir, config.sync.output_dir)
    with FileLock(lock_store.lock_dir):
        jwt_token = build_jwt(config)
        summary = SyncSummary(dry_run=dry_run)
        with enable_client(config, jwt_token) as client:
            for session_alias in session_aliases:
                store = SessionStore(config.sync.state_dir, config.sync.output_dir, session_alias)
                session = store.load_active_session()
                checkpoints = store.load_checkpoints()
                remote_session = client.get_session(session.session.session_id)
                session.session.status = remote_session.get("status", session.session.status)
                session.session.valid_until = remote_session.get("valid_until") or remote_session.get("expires_at")
                ensure_session_usable(session.session.status)
                accounts = _select_accounts(session.accounts, all_accounts, selected_accounts)
                logger.info(
                    "sync_started",
                    extra={
                        "event": "sync_started",
                        "session": session_alias,
                        "account_count": len(accounts),
                        "dry_run": dry_run,
                    },
                )
                for account in accounts:
                    try:
                        fetch_run_id = str(uuid4())
                        fetched_at = iso_now()
                        balances_payload = client.get_account_balances(account.provider_account_uid)
                        balance_records = normalize_balances(
                            session,
                            account,
                            balances_payload,
                            fetched_at=fetched_at,
                            fetch_run_id=fetch_run_id,
                        )
                        if not dry_run:
                            store.archive_raw("balances", account.account_key, utc_now(), balances_payload)
                            store.append_normalized("balances", account.account_key, balance_records)
                        summary.balances_accounts += 1
                        summary.balances_records += len(balance_records)

                        checkpoint = checkpoints.accounts.get(account.account_key)
                        window = derive_fetch_window(
                            checkpoint,
                            overlap_days=config.sync.overlap_days,
                            explicit_from=None,
                            explicit_to=None,
                            initial_lookback_days=config.sync.initial_lookback_days,
                        )
                        transaction_records: list[dict] = []
                        page_index = 0
                        for page in client.iter_transactions(
                            account.provider_account_uid,
                            date_from=window.from_date.isoformat(),
                            date_to=window.to_date.isoformat(),
                        ):
                            page_index += 1
                            normalized = normalize_transactions_page(
                                session,
                                account,
                                page,
                                fetched_at=fetched_at,
                                fetch_run_id=fetch_run_id,
                            )
                            transaction_records.extend(normalized)
                            if not dry_run:
                                store.archive_raw(
                                    "transactions",
                                    account.account_key,
                                    utc_now(),
                                    page,
                                    page_number=page_index,
                                )
                        latest_records = dedupe_transactions(
                            store.read_latest_transactions(account.account_key) + transaction_records
                        )
                        if not dry_run:
                            store.append_normalized("transactions", account.account_key, transaction_records)
                            store.write_latest_transactions(account.account_key, latest_records)
                            checkpoints.accounts[account.account_key] = update_checkpoint_from_records(
                                checkpoint,
                                latest_records,
                                from_date=window.from_date,
                                to_date=window.to_date,
                                synced_at=fetched_at,
                            )
                        summary.transactions_accounts += 1
                        summary.transactions_records += len(transaction_records)
                        logger.info(
                            "account_synced",
                            extra={
                                "event": "account_synced",
                                "session": session_alias,
                                "account_key": account.account_key,
                                "balance_count": len(balance_records),
                                "transaction_count": len(transaction_records),
                            },
                        )
                    except Exception:  # noqa: BLE001
                        summary.failed_accounts.append(f"{session_alias}:{account.account_key}")
                        logger.exception(
                            "account_sync_failed",
                            extra={
                                "event": "account_sync_failed",
                                "session": session_alias,
                                "account_key": account.account_key,
                            },
                        )
                        if fail_fast:
                            raise
                if not dry_run:
                    store.save_checkpoints(checkpoints)
                    store.save_active_session(session)
            logger.info(
                "sync_completed",
                extra={
                    "event": "sync_completed",
                    "sessions": session_aliases,
                    "failed_accounts": summary.failed_accounts,
                    "balances_records": summary.balances_records,
                    "transactions_records": summary.transactions_records,
                },
            )
            if summary.failed_accounts and (
                summary.balances_accounts > len(summary.failed_accounts)
                or summary.transactions_accounts > len(summary.failed_accounts)
            ):
                raise PartialSyncError("sync completed with partial failures")
            if summary.failed_accounts:
                raise SessionInvalidError("sync failed for all requested accounts")
            return summary


def _select_accounts(
    accounts: list[AccountState],
    all_accounts: bool,
    selected_accounts: list[str] | None,
) -> list[AccountState]:
    if all_accounts:
        return accounts
    wanted = set(selected_accounts or [])
    return [account for account in accounts if account.account_key in wanted]
