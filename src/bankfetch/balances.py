from __future__ import annotations

from datetime import datetime

from .models import AccountState, ActiveSession, BalanceRecord


def normalize_balances(
    session: ActiveSession,
    account: AccountState,
    balances_payload: dict,
    *,
    fetched_at: str,
    fetch_run_id: str,
) -> list[dict]:
    records: list[dict] = []
    for balance in balances_payload.get("balances", []):
        amount = balance.get("balance_amount") or {}
        record = BalanceRecord(
            bank=session.bank,
            session_id=session.session.session_id,
            account_key=account.account_key,
            provider_account_uid=account.provider_account_uid,
            fetch_run_id=fetch_run_id,
            fetched_at=fetched_at,
            balance_type=balance.get("balance_type"),
            balance_name=balance.get("name"),
            amount=str(amount.get("amount")),
            currency=str(amount.get("currency") or account.currency or ""),
            credit_debit_indicator=balance.get("credit_debit_indicator"),
            reference_date=balance.get("reference_date"),
        )
        records.append(record.model_dump(mode="json"))
    return records

