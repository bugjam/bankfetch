from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .models import AppConfig
from .utils import ensure_directory

DEFAULT_CONFIG_PATH = Path("/etc/bankfetch/config.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ConfigError("configuration root must be a mapping")
    return payload


def _is_writable_directory(path: Path) -> bool:
    try:
        ensure_directory(path)
    except OSError as exc:
        raise ConfigError(f"unable to create directory {path}: {exc}") from exc
    return os.access(path, os.W_OK)


def validate_config(config: AppConfig) -> AppConfig:
    if config.provider != "enable_banking":
        raise ConfigError("provider must be enable_banking in v1")
    key_path = config.api.private_key_file
    if not key_path.exists():
        raise ConfigError(f"private key file does not exist: {key_path}")
    if not key_path.is_file():
        raise ConfigError(f"private key file is not a file: {key_path}")
    try:
        key_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"private key file is not readable: {key_path}") from exc
    if not _is_writable_directory(config.sync.state_dir):
        raise ConfigError(f"state_dir is not writable: {config.sync.state_dir}")
    if not _is_writable_directory(config.sync.output_dir):
        raise ConfigError(f"output_dir is not writable: {config.sync.output_dir}")
    return config


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"config file does not exist: {config_path}")
    try:
        payload = _load_yaml(config_path)
        config = AppConfig.model_validate(payload)
    except ConfigError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"invalid configuration: {exc}") from exc
    return validate_config(config)

