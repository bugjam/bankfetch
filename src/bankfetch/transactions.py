from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, timedelta
from typing import Any

from .errors import DataValidationError
from .models import AccountCheckpoint, AccountState, ActiveSession, TransactionFetchWindow, TransactionRecord
from .utils import parse_date, sha256_text, utc_now


def derive_fetch_window(
    checkpoint: AccountCheckpoint | None,
    *,
    overlap_days: int,
    explicit_from: date | None,
    explicit_to: date | None,
    initial_lookback_days: int | None = None,
    today: date | None = None,
) -> TransactionFetchWindow:
    today = today or utc_now().date()
    if explicit_from and explicit_to:
        return TransactionFetchWindow(from_date=explicit_from, to_date=explicit_to)
    if explicit_from and not explicit_to:
        return TransactionFetchWindow(from_date=explicit_from, to_date=today)
    if checkpoint and checkpoint.last_booked_date:
        from_date = parse_date(checkpoint.last_booked_date) - timedelta(days=overlap_days)
        to_date = explicit_to or today
        return TransactionFetchWindow(from_date=from_date, to_date=to_date)
    if initial_lookback_days is not None:
        from_date = today - timedelta(days=initial_lookback_days)
        to_date = explicit_to or today
        return TransactionFetchWindow(from_date=from_date, to_date=to_date)
    raise DataValidationError(
        "initial transaction fetch requires --from or a configured initial_lookback_days"
    )


def transaction_dedupe_key(
    provider: str,
    aspsp_id: str,
    provider_account_uid: str,
    transaction: dict[str, Any],
) -> str:
    transaction_id = transaction.get("transaction_id") or transaction.get("transactionId")
    if transaction_id:
        return f"transaction_id:{transaction_id}"
    entry_reference = transaction.get("entry_reference")
    if entry_reference:
        return f"entry_reference:{entry_reference}"
    amount = transaction.get("transaction_amount") or transaction.get("amount") or {}
    creditor = transaction.get("creditor_name") or transaction.get("debtor_name")
    remittance = _extract_remittance_information(transaction)
    return sha256_text(
        [
            provider,
            aspsp_id,
            provider_account_uid,
            transaction.get("booking_date"),
            transaction.get("value_date"),
            str(amount.get("amount")),
            str(amount.get("currency")),
            transaction.get("credit_debit_indicator"),
            creditor,
            remittance,
            transaction.get("entry_reference"),
        ]
    )


def normalize_transactions_page(
    session: ActiveSession,
    account: AccountState,
    payload: dict[str, Any],
    *,
    fetched_at: str,
    fetch_run_id: str,
    status_filter: str = "both",
) -> list[dict[str, Any]]:
    source = _extract_transactions(payload, status_filter=status_filter)
    records: list[dict[str, Any]] = []
    for item in source:
        amount = item.get("transaction_amount") or item.get("amount") or {}
        record = TransactionRecord(
            bank=session.bank,
            session_id=session.session.session_id,
            account_key=account.account_key,
            provider_account_uid=account.provider_account_uid,
            fetch_run_id=fetch_run_id,
            fetched_at=fetched_at,
            transaction_id=item.get("transaction_id") or item.get("transactionId"),
            entry_reference=item.get("entry_reference"),
            transaction_status=item.get("status") or item.get("transaction_status"),
            booking_date=item.get("booking_date"),
            value_date=item.get("value_date"),
            amount=str(amount.get("amount")),
            currency=str(amount.get("currency") or account.currency or ""),
            credit_debit_indicator=item.get("credit_debit_indicator"),
            counterparty_name=_extract_counterparty_name(item),
            remittance_information=_extract_remittance_information(item),
            proprietary_bank_transaction_code=_extract_transaction_code(item),
            dedupe_key=transaction_dedupe_key(
                session.provider,
                session.bank.aspsp_id,
                account.provider_account_uid,
                item,
            ),
        )
        records.append(record.model_dump(mode="json"))
    return records


def dedupe_transactions(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped[record["dedupe_key"]] = record
    return list(deduped.values())


def update_checkpoint_from_records(
    checkpoint: AccountCheckpoint | None,
    records: list[dict[str, Any]],
    *,
    from_date: date,
    to_date: date,
    synced_at: str,
) -> AccountCheckpoint:
    current = checkpoint or AccountCheckpoint()
    booked_dates = [record["booking_date"] for record in records if record.get("booking_date")]
    pending_dates = [
        record["booking_date"]
        for record in records
        if (record.get("transaction_status") or "").lower().startswith("pend") and record.get("booking_date")
    ]
    return AccountCheckpoint(
        last_successful_sync_at=synced_at,
        last_booked_date=max(booked_dates) if booked_dates else current.last_booked_date,
        last_pending_date=max(pending_dates) if pending_dates else current.last_pending_date,
        last_fetch_from=from_date.isoformat(),
        last_fetch_to=to_date.isoformat(),
    )


def _extract_transactions(payload: dict[str, Any], *, status_filter: str) -> list[dict[str, Any]]:
    transactions = payload.get("transactions", {})
    if isinstance(transactions, list):
        if status_filter == "both":
            return transactions
        wanted = "BOOK" if status_filter == "booked" else "PENDING"
        return [item for item in transactions if (item.get("status") or "").upper().startswith(wanted)]
    source: list[dict[str, Any]] = []
    if status_filter in {"booked", "both"}:
        source.extend(transactions.get("booked", []))
    if status_filter in {"pending", "both"}:
        source.extend(transactions.get("pending", []))
    return source


def _extract_remittance_information(transaction: dict[str, Any]) -> str | None:
    remittance = transaction.get("remittance_information_unstructured")
    if remittance:
        if isinstance(remittance, list):
            return " ".join(str(part) for part in remittance)
        return str(remittance)
    remittance = transaction.get("remittance_information")
    if isinstance(remittance, list):
        return " ".join(str(part) for part in remittance)
    if remittance is not None:
        return str(remittance)
    note = transaction.get("note")
    return str(note) if note is not None else None


def _extract_counterparty_name(transaction: dict[str, Any]) -> str | None:
    direct = transaction.get("creditor_name") or transaction.get("debtor_name")
    if direct:
        return str(direct)
    creditor = transaction.get("creditor") or {}
    debtor = transaction.get("debtor") or {}
    nested = creditor.get("name") or debtor.get("name")
    return str(nested) if nested else None


def _extract_transaction_code(transaction: dict[str, Any]) -> str | None:
    direct = transaction.get("proprietary_bank_transaction_code")
    if direct:
        return str(direct)
    bank_code = transaction.get("bank_transaction_code") or {}
    return bank_code.get("description") or bank_code.get("code") or bank_code.get("sub_code")
