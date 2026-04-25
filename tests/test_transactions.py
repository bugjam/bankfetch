from __future__ import annotations

from datetime import date

import pytest

from bankfetch.errors import DataValidationError
from bankfetch.models import AccountCheckpoint
from bankfetch.transactions import dedupe_transactions, derive_fetch_window, transaction_dedupe_key, update_checkpoint_from_records


def test_dedupe_prefers_transaction_id() -> None:
    key = transaction_dedupe_key(
        "enable_banking",
        "bank-1",
        "acct-1",
        {"transaction_id": "tx-1", "entry_reference": "entry-1"},
    )
    assert key == "transaction_id:tx-1"


def test_dedupe_falls_back_to_hash() -> None:
    key = transaction_dedupe_key(
        "enable_banking",
        "bank-1",
        "acct-1",
        {
            "booking_date": "2026-04-10",
            "value_date": "2026-04-10",
            "transaction_amount": {"amount": "-10.00", "currency": "DKK"},
            "credit_debit_indicator": "DBIT",
            "creditor_name": "Shop",
            "remittance_information": "Card",
        },
    )
    assert key.startswith("sha256:")


def test_dedupe_uses_entry_reference_when_transaction_id_missing() -> None:
    key = transaction_dedupe_key(
        "enable_banking",
        "bank-1",
        "acct-1",
        {"entry_reference": "entry-1"},
    )
    assert key == "entry_reference:entry-1"


def test_initial_fetch_requires_from_or_lookback() -> None:
    with pytest.raises(DataValidationError):
        derive_fetch_window(None, overlap_days=3, explicit_from=None, explicit_to=None, initial_lookback_days=None)


def test_incremental_fetch_uses_overlap() -> None:
    window = derive_fetch_window(
        AccountCheckpoint(last_booked_date="2026-04-10"),
        overlap_days=3,
        explicit_from=None,
        explicit_to=None,
        today=date(2026, 4, 18),
    )
    assert window.from_date == date(2026, 4, 7)
    assert window.to_date == date(2026, 4, 18)


def test_dedupe_transactions_keeps_single_record_per_key() -> None:
    records = dedupe_transactions(
        [
            {"dedupe_key": "one", "amount": "1"},
            {"dedupe_key": "one", "amount": "2"},
            {"dedupe_key": "two", "amount": "3"},
        ]
    )
    assert len(records) == 2


def test_dedupe_transactions_merges_semantic_duplicates_with_changed_entry_reference() -> None:
    records = dedupe_transactions(
        [
            {
                "account_key": "enable_banking:nordea-dk:acct-1",
                "amount": "39700.44",
                "booking_date": "2026-04-23",
                "counterparty_name": "GIRO-CARD",
                "credit_debit_indicator": "DBIT",
                "currency": "DKK",
                "dedupe_key": "entry_reference:H90368264920000000091",
                "entry_reference": "H90368264920000000091",
                "fetched_at": "2026-04-24T14:00:35.066997Z",
                "proprietary_bank_transaction_code": "BGS",
                "remittance_information": "Bgs Sydporten",
                "transaction_id": None,
                "value_date": "2026-04-23",
            },
            {
                "account_key": "enable_banking:nordea-dk:acct-1",
                "amount": "39700.44",
                "booking_date": "2026-04-23",
                "counterparty_name": "GIRO-CARD",
                "credit_debit_indicator": "DBIT",
                "currency": "DKK",
                "dedupe_key": "entry_reference:P9036826492202604230000000090",
                "entry_reference": "P9036826492202604230000000090",
                "fetched_at": "2026-04-25T04:00:14.882870Z",
                "proprietary_bank_transaction_code": "BGS",
                "remittance_information": "Bgs Sydporten",
                "transaction_id": None,
                "value_date": "2026-04-23",
            },
        ]
    )
    assert len(records) == 1
    assert records[0]["entry_reference"] == "P9036826492202604230000000090"


def test_update_checkpoint_tracks_last_fetch_dates() -> None:
    checkpoint = update_checkpoint_from_records(
        None,
        [
            {"booking_date": "2026-04-12", "transaction_status": "BOOK"},
            {"booking_date": "2026-04-13", "transaction_status": "PENDING"},
        ],
        from_date=date(2026, 4, 10),
        to_date=date(2026, 4, 18),
        synced_at="2026-04-18T10:00:00Z",
    )
    assert checkpoint.last_successful_sync_at == "2026-04-18T10:00:00Z"
    assert checkpoint.last_booked_date == "2026-04-13"
    assert checkpoint.last_pending_date == "2026-04-13"
