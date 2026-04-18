from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import jwt

from .errors import JwtSigningError
from .models import AppConfig


def build_jwt(config: AppConfig, ttl_seconds: int = 300) -> str:
    try:
        private_key = config.api.private_key_file.read_text(encoding="utf-8")
        now = datetime.now(tz=UTC)
        audience = urlparse(config.api.base_url).netloc or config.api.base_url.rstrip("/")
        payload = {
            "iss": "enablebanking.com",
            "aud": audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "jti": str(uuid4()),
        }
        headers = {"kid": config.api.app_id}
        return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise JwtSigningError(f"unable to sign JWT: {exc}") from exc
