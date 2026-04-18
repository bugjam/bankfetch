from __future__ import annotations

import json
from pathlib import Path

import yaml

from bankfetch.cli import _access_valid_until, app


def _seed_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    session_payload = {
        "provider": "enable_banking",
        "bank": {"aspsp_id": "bank-1", "display_name": "Nordea", "country_code": "DK"},
        "session": {"session_id": "sess-1", "status": "AUTHORIZED", "valid_until": "2026-07-15T12:00:00Z"},
        "accounts": [
            {
                "account_key": "enable_banking:bank-1:acct-1",
                "provider_account_uid": "acct-1",
                "display_name": "Main",
                "currency": "DKK",
                "account_type": "payment",
                "identifiers": {"iban_masked": "DK12****34", "other_masked": []},
            }
        ],
    }
    checkpoints_payload = {"version": 1, "accounts": {}}
    (state_dir / "active_session.json").write_text(yaml.safe_dump(session_payload), encoding="utf-8")
    (state_dir / "checkpoints.json").write_text(yaml.safe_dump(checkpoints_payload), encoding="utf-8")


def test_auth_init_command(runner, config_file: Path, mocker, respx_mock) -> None:
    mocker.patch("bankfetch.cli.build_jwt", return_value="jwt")
    captured = {}

    def assert_auth_request(request):
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return __import__("httpx").Response(
            200,
            json={"url": "https://example.test/auth", "authorization_id": "auth-1", "psu_id_hash": "hash"},
        )

    respx_mock.get("https://api.enablebanking.com/aspsps").respond(
        200,
        json={"aspsps": [{"id": "bank-1", "name": "Nordea", "country": "DK", "maximum_consent_validity": 3600}]},
    )
    respx_mock.post("https://api.enablebanking.com/auth").mock(side_effect=assert_auth_request)
    result = runner.invoke(app, ["--config", str(config_file), "auth", "init"])
    assert result.exit_code == 0
    assert "Authorization URL: https://example.test/auth" in result.stdout
    assert "valid_until" in captured["json"]["access"]


def test_auth_init_command_without_aspsp_id_uses_provider_object(runner, config_file: Path, mocker, respx_mock) -> None:
    mocker.patch("bankfetch.cli.build_jwt", return_value="jwt")
    captured = {}

    def assert_auth_request(request):
        captured["json"] = request.content.decode("utf-8")
        return __import__("httpx").Response(
            200,
            json={"url": "https://example.test/auth", "authorization_id": "auth-1", "psu_id_hash": "hash"},
        )

    respx_mock.get("https://api.enablebanking.com/aspsps").respond(
        200,
        json={
            "aspsps": [
                {
                    "name": "Nordea",
                    "country": "DK",
                    "bic": "NDEADKKK",
                    "auth_methods": [{"name": "MTA", "approach": "REDIRECT"}],
                }
            ]
        },
    )
    respx_mock.post("https://api.enablebanking.com/auth").mock(side_effect=assert_auth_request)
    result = runner.invoke(app, ["--config", str(config_file), "auth", "init"])
    assert result.exit_code == 0
    assert '"name":"Nordea"' in captured["json"]
    assert '"country":"DK"' in captured["json"]
    assert '"valid_until"' in captured["json"]


def test_access_valid_until_is_capped_by_aspsp_limit() -> None:
    valid_until = _access_valid_until(90, {"maximum_consent_validity": 3600})
    assert valid_until.endswith("+00:00")


def test_session_status_reauth_exit_code(runner, config_file: Path, mocker, respx_mock) -> None:
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    state_dir = Path(config["sync"]["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    active_session = {
        "provider": "enable_banking",
        "bank": {"aspsp_id": "bank-1", "display_name": "Nordea", "country_code": "DK"},
        "session": {"session_id": "sess-1", "status": "AUTHORIZED", "valid_until": None, "created_at": None},
        "accounts": [],
    }
    (state_dir / "active_session.json").write_text(__import__("json").dumps(active_session), encoding="utf-8")
    mocker.patch("bankfetch.cli.build_jwt", return_value="jwt")
    respx_mock.get("https://api.enablebanking.com/sessions/sess-1").respond(200, json={"status": "EXPIRED"})
    result = runner.invoke(app, ["--config", str(config_file), "session", "status"])
    assert result.exit_code == 20


def test_accounts_list_command(runner, config_file: Path) -> None:
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    state_dir = Path(config["sync"]["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    active_session = {
        "provider": "enable_banking",
        "bank": {"aspsp_id": "bank-1", "display_name": "Nordea", "country_code": "DK"},
        "session": {"session_id": "sess-1", "status": "AUTHORIZED", "valid_until": None, "created_at": None},
        "accounts": [
            {
                "account_key": "enable_banking:bank-1:acct-1",
                "provider_account_uid": "acct-1",
                "display_name": "Main",
                "currency": "DKK",
                "account_type": "payment",
                "identifiers": {"iban_masked": "DK12****34", "other_masked": []},
            }
        ],
    }
    (state_dir / "active_session.json").write_text(__import__("json").dumps(active_session), encoding="utf-8")
    result = runner.invoke(app, ["--config", str(config_file), "accounts", "list"])
    assert result.exit_code == 0
    assert "enable_banking:bank-1:acct-1" in result.stdout
