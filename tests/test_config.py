from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bankfetch.auth import build_jwt
from bankfetch.config import load_config
from bankfetch.errors import ConfigError, JwtSigningError


def test_load_config_validates_and_creates_dirs(config_file: Path) -> None:
    config = load_config(config_file)
    assert config.provider == "enable_banking"
    assert config.sync.state_dir.exists()
    assert config.sync.output_dir.exists()
    assert "nordea" in config.sessions


def test_load_config_rejects_missing_private_key(tmp_path: Path, config_file: Path) -> None:
    payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    payload["api"]["private_key_file"] = str(tmp_path / "missing.key")
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(broken)


def test_build_jwt_raises_signing_error_for_invalid_key(tmp_path: Path, config_file: Path) -> None:
    payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    key_path = tmp_path / "invalid.key"
    key_path.write_text("not-a-key", encoding="utf-8")
    payload["api"]["private_key_file"] = str(key_path)
    broken = tmp_path / "broken-jwt.yaml"
    broken.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config = load_config(broken)
    with pytest.raises(JwtSigningError):
        build_jwt(config)


def test_build_jwt_uses_enable_banking_issuer_and_host_audience(config_file: Path) -> None:
    config = load_config(config_file)
    captured: dict[str, object] = {}

    def fake_encode(payload, key, algorithm, headers):  # noqa: ANN001
        captured["payload"] = payload
        captured["headers"] = headers
        captured["algorithm"] = algorithm
        return "token"

    from bankfetch import auth as auth_module

    original = auth_module.jwt.encode
    auth_module.jwt.encode = fake_encode
    try:
        token = build_jwt(config)
    finally:
        auth_module.jwt.encode = original

    assert token == "token"
    assert captured["payload"]["iss"] == "enablebanking.com"
    assert captured["payload"]["aud"] == "api.enablebanking.com"
    assert captured["headers"]["kid"] == config.api.app_id
