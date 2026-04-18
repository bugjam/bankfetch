from __future__ import annotations

from . import exit_codes


class BankfetchError(Exception):
    exit_code = exit_codes.REMOTE_ERROR


class ConfigError(BankfetchError):
    exit_code = exit_codes.CONFIG_ERROR


class JwtSigningError(BankfetchError):
    exit_code = exit_codes.JWT_ERROR


class ProviderAuthorizationError(BankfetchError):
    exit_code = exit_codes.AUTHORIZATION_ERROR


class SessionInvalidError(BankfetchError):
    exit_code = exit_codes.SESSION_INVALID


class ReauthorizationRequiredError(BankfetchError):
    exit_code = exit_codes.REAUTH_REQUIRED


class RemoteApiError(BankfetchError):
    exit_code = exit_codes.REMOTE_ERROR


class DataValidationError(BankfetchError):
    exit_code = exit_codes.DATA_ERROR


class PartialSyncError(BankfetchError):
    exit_code = exit_codes.PARTIAL_SYNC


class LockContentionError(BankfetchError):
    exit_code = exit_codes.LOCK_CONTENTION

