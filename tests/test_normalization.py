from __future__ import annotations

from bankfetch.balances import normalize_balances
from bankfetch.models import AccountState, ActiveSession, BankIdentity, SessionMetadata
from bankfetch.transactions import normalize_transactions_page


def session_fixture() -> tuple[ActiveSession, AccountState]:
    bank = BankIdentity(aspsp_id="bank-1", display_name="Nordea", country_code="DK")
    account = AccountState(
        account_key="enable_banking:bank-1:acct-1",
        provider_account_uid="acct-1",
        display_name="Main",
        currency="DKK",
        account_type="payment",
    )
    session = ActiveSession(
        bank=bank,
        session=SessionMetadata(session_id="sess-1", status="AUTHORIZED"),
        accounts=[account],
    )
    return session, account


def test_balance_normalization_shape() -> None:
    session, account = session_fixture()
    records = normalize_balances(
        session,
        account,
        {
            "balances": [
                {
                    "name": "Booked balance",
                    "balance_amount": {"amount": "123.45", "currency": "DKK"},
                    "balance_type": "CLAV",
                    "reference_date": "2026-04-18",
                }
            ]
        },
        fetched_at="2026-04-18T10:00:00Z",
        fetch_run_id="run-1",
    )
    assert records[0]["provider"] == "enable_banking"
    assert records[0]["bank"]["aspsp_id"] == "bank-1"
    assert records[0]["account_key"] == "enable_banking:bank-1:acct-1"


def test_transaction_normalization_shape() -> None:
    session, account = session_fixture()
    records = normalize_transactions_page(
        session,
        account,
        {
            "transactions": {
                "booked": [
                    {
                        "transaction_id": "tx-1",
                        "entry_reference": "er-1",
                        "status": "BOOK",
                        "booking_date": "2026-04-18",
                        "value_date": "2026-04-18",
                        "transaction_amount": {"amount": "-10.00", "currency": "DKK"},
                        "credit_debit_indicator": "DBIT",
                        "creditor_name": "Shop",
                        "remittance_information": "Card purchase",
                    }
                ]
            }
        },
        fetched_at="2026-04-18T10:00:00Z",
        fetch_run_id="run-1",
    )
    assert records[0]["provider"] == "enable_banking"
    assert records[0]["transaction_id"] == "tx-1"
    assert records[0]["dedupe_key"] == "transaction_id:tx-1"


def test_transaction_normalization_handles_flat_transaction_list() -> None:
    session, account = session_fixture()
    records = normalize_transactions_page(
        session,
        account,
        {
            "transactions": [
                {
                    "transaction_id": None,
                    "entry_reference": "er-2",
                    "status": "BOOK",
                    "booking_date": "2026-04-18",
                    "value_date": "2026-04-18",
                    "transaction_amount": {"amount": "-10.00", "currency": "DKK"},
                    "credit_debit_indicator": "DBIT",
                    "creditor": {"name": "Shop"},
                    "remittance_information": ["Card purchase"],
                    "bank_transaction_code": {"description": "BGS", "code": None, "sub_code": None},
                }
            ]
        },
        fetched_at="2026-04-18T10:00:00Z",
        fetch_run_id="run-1",
    )
    assert records[0]["entry_reference"] == "er-2"
    assert records[0]["counterparty_name"] == "Shop"
    assert records[0]["remittance_information"] == "Card purchase"
    assert records[0]["proprietary_bank_transaction_code"] == "BGS"
