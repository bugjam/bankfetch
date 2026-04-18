from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .utils import mask_identifier


class ApiConfig(BaseModel):
    base_url: str = "https://api.enablebanking.com"
    app_id: str
    private_key_file: Path
    timeout_seconds: int = 30

    @field_validator("timeout_seconds")
    @classmethod
    def timeout_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value


class AspspConfig(BaseModel):
    id: str | None = None
    name: str | None = None
    country: str | None = None


class BankConfig(BaseModel):
    aspsp: AspspConfig
    psu_type: str | None = "personal"
    redirect_url: HttpUrl
    consent_days: int = 90

    @field_validator("consent_days")
    @classmethod
    def consent_days_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("consent_days must be positive")
        return value


class SyncConfig(BaseModel):
    overlap_days: int = 3
    output_dir: Path = Path("/var/lib/bankfetch/out")
    state_dir: Path = Path("/var/lib/bankfetch/state")
    raw_archive: bool = True
    normalized_format: Literal["jsonl"] = "jsonl"
    initial_lookback_days: int | None = None

    @field_validator("overlap_days")
    @classmethod
    def overlap_days_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("overlap_days must be non-negative")
        return value


class LoggingConfig(BaseModel):
    format: Literal["json"] = "json"
    level: str = "info"


class HeadersConfig(BaseModel):
    psu_ip_address: str | None = None
    psu_user_agent: str | None = "bankfetch/0.1"
    psu_referer: str | None = None
    psu_accept: str | None = None
    psu_accept_charset: str | None = None
    psu_accept_encoding: str | None = None
    psu_accept_language: str | None = None
    psu_geo_location: str | None = None


class SessionConfig(BaseModel):
    bank: BankConfig


class AppConfig(BaseModel):
    app_name: str = "bankfetch"
    provider: Literal["enable_banking"] = "enable_banking"
    api: ApiConfig
    bank: BankConfig | None = None
    sessions: dict[str, SessionConfig] = Field(default_factory=dict)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    headers: HeadersConfig = Field(default_factory=HeadersConfig)

    @model_validator(mode="after")
    def ensure_sessions(self) -> "AppConfig":
        if not self.sessions:
            if self.bank is None:
                raise ValueError("configuration must define either bank or sessions")
            self.sessions = {"default": SessionConfig(bank=self.bank)}
        return self

    def get_session_config(self, alias: str) -> SessionConfig:
        return self.sessions[alias]


class BankIdentity(BaseModel):
    aspsp_id: str
    display_name: str | None = None
    country_code: str | None = None


class AccountIdentifiers(BaseModel):
    iban_masked: str | None = None
    other_masked: list[str] = Field(default_factory=list)


class AccountState(BaseModel):
    account_key: str
    provider_account_uid: str
    display_name: str | None = None
    currency: str | None = None
    account_type: str | None = None
    identifiers: AccountIdentifiers = Field(default_factory=AccountIdentifiers)

    @classmethod
    def from_provider(cls, provider: str, bank: BankIdentity, account: dict[str, Any]) -> "AccountState":
        account_uid = str(account.get("uid") or account.get("account_uid") or account.get("account_id"))
        account_id = account.get("account_id") or {}
        iban = account_id.get("iban") if isinstance(account_id, dict) else None
        all_ids = account.get("all_account_ids") or []
        masked_other = []
        for item in all_ids:
            ident = item.get("identification")
            if ident:
                masked_other.append(mask_identifier(str(ident)) or "")
        return cls(
            account_key=f"{provider}:{bank.aspsp_id}:{account_uid}",
            provider_account_uid=account_uid,
            display_name=account.get("name") or account.get("display_name"),
            currency=account.get("currency"),
            account_type=account.get("cash_account_type") or account.get("account_type"),
            identifiers=AccountIdentifiers(
                iban_masked=mask_identifier(iban) if iban else None,
                other_masked=[value for value in masked_other if value],
            ),
        )


class SessionMetadata(BaseModel):
    session_id: str
    status: str
    valid_until: str | None = None
    created_at: str | None = None
    authorized_at: str | None = None


class ActiveSession(BaseModel):
    provider: Literal["enable_banking"] = "enable_banking"
    bank: BankIdentity
    session: SessionMetadata
    accounts: list[AccountState] = Field(default_factory=list)


class AuthInitState(BaseModel):
    provider: Literal["enable_banking"] = "enable_banking"
    bank: BankIdentity
    authorization_id: str | None = None
    authorization_url: str
    state: str
    created_at: str
    psu_id_hash: str | None = None


class AccountCheckpoint(BaseModel):
    last_successful_sync_at: str | None = None
    last_booked_date: str | None = None
    last_pending_date: str | None = None
    last_fetch_from: str | None = None
    last_fetch_to: str | None = None


class Checkpoints(BaseModel):
    version: int = 1
    accounts: dict[str, AccountCheckpoint] = Field(default_factory=dict)


class BalanceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_type: Literal["balance"] = "balance"
    provider: Literal["enable_banking"] = "enable_banking"
    bank: BankIdentity
    session_id: str
    account_key: str
    provider_account_uid: str
    fetch_run_id: str
    fetched_at: str
    balance_type: str | None = None
    balance_name: str | None = None
    amount: str
    currency: str
    credit_debit_indicator: str | None = None
    reference_date: str | None = None
    provider_payload_version: int = 1


class TransactionRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_type: Literal["transaction"] = "transaction"
    provider: Literal["enable_banking"] = "enable_banking"
    bank: BankIdentity
    session_id: str
    account_key: str
    provider_account_uid: str
    fetch_run_id: str
    fetched_at: str
    transaction_id: str | None = None
    entry_reference: str | None = None
    transaction_status: str | None = None
    booking_date: str | None = None
    value_date: str | None = None
    amount: str
    currency: str
    credit_debit_indicator: str | None = None
    counterparty_name: str | None = None
    remittance_information: str | None = None
    proprietary_bank_transaction_code: str | None = None
    provider_payload_version: int = 1
    dedupe_key: str


class SyncSummary(BaseModel):
    balances_accounts: int = 0
    balances_records: int = 0
    transactions_accounts: int = 0
    transactions_records: int = 0
    failed_accounts: list[str] = Field(default_factory=list)
    dry_run: bool = False


class TransactionFetchWindow(BaseModel):
    from_date: date
    to_date: date
