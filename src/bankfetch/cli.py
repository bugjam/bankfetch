from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from . import exit_codes
from .auth import build_jwt
from .balances import normalize_balances
from .config import DEFAULT_CONFIG_PATH, load_config
from .enable_client import enable_client
from .errors import BankfetchError, PartialSyncError, ReauthorizationRequiredError, SessionInvalidError
from .logging import configure_logging, get_logger
from .models import AccountState, ActiveSession, AuthInitState, BankIdentity, Checkpoints, SessionMetadata
from .session_store import SessionStore
from .sync import ensure_session_usable, run_sync
from .transactions import dedupe_transactions, derive_fetch_window, normalize_transactions_page, update_checkpoint_from_records
from .utils import iso_now, parse_date, sanitize_filename, utc_now

app = typer.Typer(help="Fetch account data from Enable Banking")
auth_app = typer.Typer()
session_app = typer.Typer()
accounts_app = typer.Typer()
balances_app = typer.Typer()
transactions_app = typer.Typer()
sync_app = typer.Typer()

app.add_typer(auth_app, name="auth")
app.add_typer(session_app, name="session")
app.add_typer(accounts_app, name="accounts")
app.add_typer(balances_app, name="balances")
app.add_typer(transactions_app, name="transactions")
app.add_typer(sync_app, name="sync")


class Context:
    def __init__(self) -> None:
        self.config_path: Path = DEFAULT_CONFIG_PATH


def _config_and_store(ctx: typer.Context):
    state: Context = ctx.obj
    config = load_config(state.config_path)
    configure_logging(config.logging.level)
    return config


@app.callback()
def main_callback(
    ctx: typer.Context,
    config: Annotated[Path, typer.Option("--config", help="Path to config file")] = DEFAULT_CONFIG_PATH,
) -> None:
    ctx.obj = Context()
    ctx.obj.config_path = config


@auth_app.command("init")
def auth_init(
    ctx: typer.Context,
    session: Annotated[str | None, typer.Option("--session", help="Configured session profile")] = None,
) -> None:
    config = _config_and_store(ctx)
    session_alias = _resolve_session_alias(config, session)
    store = _session_store(config, session_alias)
    session_config = config.get_session_config(session_alias)
    jwt_token = build_jwt(config)
    with enable_client(config, jwt_token) as client:
        aspsp = _resolve_aspsp(session_config.bank, client.list_aspsps())
        aspsp_id = _aspsp_identifier(aspsp)
        state = str(uuid4())
        payload = {
            "access": {
                "balances": True,
                "transactions": True,
                "valid_until": _access_valid_until(session_config.bank.consent_days, aspsp),
            },
            "aspsp": aspsp,
            "state": state,
            "redirect_url": str(session_config.bank.redirect_url),
            "psu_type": session_config.bank.psu_type,
        }
        response = client.start_authorization(payload)
    auth_state = AuthInitState(
        bank=BankIdentity(
            aspsp_id=aspsp_id,
            display_name=aspsp.get("name"),
            country_code=aspsp.get("country"),
        ),
        authorization_id=response.get("authorization_id"),
        authorization_url=response["url"],
        state=state,
        created_at=iso_now(),
        psu_id_hash=response.get("psu_id_hash"),
    )
    store.save_auth_init(auth_state)
    typer.echo(f"Session: {session_alias}")
    typer.echo(f"Authorization URL: {auth_state.authorization_url}")
    typer.echo(f"State: {auth_state.state}")
    typer.echo(f"Created at: {auth_state.created_at}")


@auth_app.command("complete")
def auth_complete(
    ctx: typer.Context,
    code: Annotated[str, typer.Option("--code", help="Authorization code", prompt=False)],
    session: Annotated[str | None, typer.Option("--session", help="Configured session profile")] = None,
) -> None:
    config = _config_and_store(ctx)
    session_alias = _resolve_session_alias(config, session)
    store = _session_store(config, session_alias)
    auth_state = store.load_auth_init()
    jwt_token = build_jwt(config)
    with enable_client(config, jwt_token) as client:
        response = client.authorize_session(code)
        session_id = response["session_id"]
        session_payload = client.get_session(session_id)
    bank = BankIdentity(
        aspsp_id=_aspsp_identifier(response.get("aspsp", {}), fallback=auth_state.bank.aspsp_id),
        display_name=response.get("aspsp", {}).get("name", auth_state.bank.display_name),
        country_code=response.get("aspsp", {}).get("country", auth_state.bank.country_code),
    )
    accounts = [
        AccountState.from_provider("enable_banking", bank, account)
        for account in response.get("accounts", [])
    ]
    active_session = ActiveSession(
        bank=bank,
        session=SessionMetadata(
            session_id=session_id,
            status=session_payload.get("status", "AUTHORIZED"),
            valid_until=_session_valid_until(session_payload),
            created_at=session_payload.get("created"),
            authorized_at=session_payload.get("authorized"),
        ),
        accounts=accounts,
    )
    store.save_active_session(active_session)
    store.save_checkpoints(Checkpoints())
    typer.echo(f"Session: {session_alias}")
    typer.echo(f"Session ID: {active_session.session.session_id}")
    typer.echo(f"Status: {active_session.session.status}")
    typer.echo(f"Valid until: {active_session.session.valid_until or 'unknown'}")
    typer.echo(f"Accounts discovered: {len(active_session.accounts)}")


@session_app.command("status")
def session_status(
    ctx: typer.Context,
    session_name: Annotated[str | None, typer.Option("--session", help="Configured session profile")] = None,
) -> None:
    config = _config_and_store(ctx)
    session_alias = _resolve_session_alias(config, session_name)
    store = _session_store(config, session_alias)
    active_session = store.load_active_session()
    jwt_token = build_jwt(config)
    with enable_client(config, jwt_token) as client:
        remote = client.get_session(active_session.session.session_id)
    status = remote.get("status", active_session.session.status)
    active_session.session.status = status
    active_session.session.valid_until = _session_valid_until(remote)
    store.save_active_session(active_session)
    typer.echo(f"Session: {session_alias}")
    typer.echo("Provider: enable_banking")
    typer.echo(f"Bank: {active_session.bank.aspsp_id}")
    typer.echo(f"Session ID: {active_session.session.session_id}")
    typer.echo(f"Remote status: {status}")
    typer.echo(f"Local active: {'yes' if status in {'AUTHORIZED', 'ACTIVE'} else 'no'}")
    typer.echo(f"Valid until: {active_session.session.valid_until or 'unknown'}")
    if status in {"EXPIRED", "REVOKED"}:
        raise typer.Exit(code=exit_codes.REAUTH_REQUIRED)
    if status not in {"AUTHORIZED", "ACTIVE"}:
        raise typer.Exit(code=exit_codes.SESSION_INVALID)


@accounts_app.command("list")
def accounts_list(
    ctx: typer.Context,
    session: Annotated[str | None, typer.Option("--session", help="Configured session profile")] = None,
) -> None:
    config = _config_and_store(ctx)
    session_alias = _resolve_session_alias(config, session)
    store = _session_store(config, session_alias)
    session = store.load_active_session()
    for account in session.accounts:
        typer.echo(
            " | ".join(
                [
                    account.account_key,
                    account.provider_account_uid,
                    account.display_name or "-",
                    account.account_type or "-",
                    account.currency or "-",
                    account.identifiers.iban_masked or "-",
                ]
            )
        )


@balances_app.command("fetch")
def balances_fetch(
    ctx: typer.Context,
    session: Annotated[str | None, typer.Option("--session", help="Configured session profile")] = None,
    all_accounts: Annotated[bool, typer.Option("--all-accounts")] = False,
    account: Annotated[list[str], typer.Option("--account")] = [],
) -> None:
    config = _config_and_store(ctx)
    session_alias = _resolve_session_alias(config, session)
    store = _session_store(config, session_alias)
    session = store.load_active_session()
    jwt_token = build_jwt(config)
    with enable_client(config, jwt_token) as client:
        remote = client.get_session(session.session.session_id)
        ensure_session_usable(remote.get("status", session.session.status))
        for item in _select_accounts(session.accounts, all_accounts, account):
            payload = client.get_account_balances(item.provider_account_uid)
            fetched_at = iso_now()
            records = normalize_balances(session, item, payload, fetched_at=fetched_at, fetch_run_id=str(uuid4()))
            store.archive_raw("balances", item.account_key, utc_now(), payload)
            store.append_normalized("balances", item.account_key, records)
            typer.echo(f"{item.account_key}: fetched {len(records)} balances")


@transactions_app.command("fetch")
def transactions_fetch(
    ctx: typer.Context,
    session: Annotated[str | None, typer.Option("--session", help="Configured session profile")] = None,
    all_accounts: Annotated[bool, typer.Option("--all-accounts")] = False,
    account: Annotated[list[str], typer.Option("--account")] = [],
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
    status: Annotated[str, typer.Option("--status")] = "both",
    no_checkpoint_update: Annotated[bool, typer.Option("--no-checkpoint-update")] = False,
) -> None:
    config = _config_and_store(ctx)
    session_alias = _resolve_session_alias(config, session)
    store = _session_store(config, session_alias)
    session = store.load_active_session()
    checkpoints = store.load_checkpoints()
    jwt_token = build_jwt(config)
    with enable_client(config, jwt_token) as client:
        remote = client.get_session(session.session.session_id)
        ensure_session_usable(remote.get("status", session.session.status))
        for item in _select_accounts(session.accounts, all_accounts, account):
            checkpoint = checkpoints.accounts.get(item.account_key)
            window = derive_fetch_window(
                checkpoint,
                overlap_days=config.sync.overlap_days,
                explicit_from=parse_date(from_date) if from_date else None,
                explicit_to=parse_date(to_date) if to_date else None,
                initial_lookback_days=config.sync.initial_lookback_days,
            )
            fetched_at = iso_now()
            fetch_run_id = str(uuid4())
            page_records: list[dict] = []
            page_number = 0
            for page in client.iter_transactions(
                item.provider_account_uid,
                date_from=window.from_date.isoformat(),
                date_to=window.to_date.isoformat(),
            ):
                page_number += 1
                store.archive_raw("transactions", item.account_key, utc_now(), page, page_number=page_number)
                page_records.extend(
                    normalize_transactions_page(
                        session,
                        item,
                        page,
                        fetched_at=fetched_at,
                        fetch_run_id=fetch_run_id,
                        status_filter=status,
                    )
                )
            latest_records = dedupe_transactions(store.read_latest_transactions(item.account_key) + page_records)
            store.append_normalized("transactions", item.account_key, page_records)
            store.write_latest_transactions(item.account_key, latest_records)
            if not no_checkpoint_update:
                checkpoints.accounts[item.account_key] = update_checkpoint_from_records(
                    checkpoint,
                    latest_records,
                    from_date=window.from_date,
                    to_date=window.to_date,
                    synced_at=fetched_at,
                )
            typer.echo(f"{item.account_key}: fetched {len(page_records)} transactions")
    if not no_checkpoint_update:
        store.save_checkpoints(checkpoints)


@sync_app.command("run")
def sync_run(
    ctx: typer.Context,
    session: Annotated[list[str], typer.Option("--session", help="Configured session profile to sync")] = [],
    all_accounts: Annotated[bool, typer.Option("--all-accounts")] = False,
    fail_fast: Annotated[bool, typer.Option("--fail-fast/--no-fail-fast")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    config = _config_and_store(ctx)
    session_aliases = _session_aliases_for_sync(config, session)
    summary = run_sync(
        config,
        session_aliases=session_aliases,
        all_accounts=all_accounts,
        fail_fast=fail_fast,
        dry_run=dry_run,
    )
    typer.echo(
        f"Sync complete: balances={summary.balances_records} transactions={summary.transactions_records} failed={len(summary.failed_accounts)}"
    )


def _resolve_aspsp(bank_config, aspsps: list[dict]) -> dict:
    if bank_config.aspsp.id:
        for item in aspsps:
            if _aspsp_identifier(item) == bank_config.aspsp.id or item.get("id") == bank_config.aspsp.id:
                return item
    if bank_config.aspsp.name:
        for item in aspsps:
            matches_name = item.get("name", "").lower() == bank_config.aspsp.name.lower()
            matches_country = not bank_config.aspsp.country or item.get("country") == bank_config.aspsp.country
            if matches_name and matches_country:
                return item
    raise BankfetchError("unable to resolve configured ASPSP")


def _aspsp_identifier(aspsp: dict, fallback: str | None = None) -> str:
    identifier = aspsp.get("id") or aspsp.get("aspsp_id")
    if identifier:
        return str(identifier)
    name = aspsp.get("name")
    country = aspsp.get("country")
    bic = aspsp.get("bic")
    if name and country:
        return sanitize_filename(f"{name.lower()}-{str(country).lower()}")
    if bic:
        return str(bic).lower()
    if fallback:
        return fallback
    raise BankfetchError("resolved ASPSP does not contain a usable identifier")


def _access_valid_until(consent_days: int, aspsp: dict) -> str:
    now = utc_now()
    requested = now + timedelta(days=consent_days)
    max_seconds = aspsp.get("maximum_consent_validity")
    if isinstance(max_seconds, int) and max_seconds > 0:
        provider_limit = now + timedelta(seconds=max_seconds)
        requested = min(requested, provider_limit)
    return requested.astimezone(UTC).isoformat(timespec="seconds")


def _select_accounts(accounts: list[AccountState], all_accounts: bool, selected: list[str]) -> list[AccountState]:
    if all_accounts:
        return accounts
    wanted = set(selected)
    if not wanted:
        raise BankfetchError("select accounts with --all-accounts or --account")
    return [account for account in accounts if account.account_key in wanted]


def _session_valid_until(session_payload: dict) -> str | None:
    access = session_payload.get("access") or {}
    return access.get("valid_until") or session_payload.get("valid_until") or session_payload.get("expires_at")


def _resolve_session_alias(config, alias: str | None) -> str:
    if alias:
        if alias not in config.sessions:
            raise BankfetchError(f"unknown session profile: {alias}")
        return alias
    if len(config.sessions) == 1:
        return next(iter(config.sessions))
    available = ", ".join(sorted(config.sessions))
    raise BankfetchError(f"multiple session profiles configured; choose one with --session ({available})")


def _session_aliases_for_sync(config, aliases: list[str]) -> list[str]:
    if not aliases:
        return list(config.sessions)
    unknown = [alias for alias in aliases if alias not in config.sessions]
    if unknown:
        raise BankfetchError(f"unknown session profile(s): {', '.join(sorted(unknown))}")
    return aliases


def _session_store(config, alias: str) -> SessionStore:
    return SessionStore(config.sync.state_dir, config.sync.output_dir, alias)


def main() -> None:
    try:
        app()
    except PartialSyncError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    except BankfetchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from exc


if __name__ == "__main__":
    main()
