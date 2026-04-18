from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from .errors import ProviderAuthorizationError, RemoteApiError
from .models import AppConfig


class EnableBankingClient:
    def __init__(self, config: AppConfig, jwt_token: str):
        self.config = config
        self.jwt_token = jwt_token
        self._client = httpx.Client(
            base_url=config.api.base_url.rstrip("/"),
            timeout=config.api.timeout_seconds,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        cfg = self.config.headers
        optional_headers = {
            "Psu-Ip-Address": cfg.psu_ip_address,
            "Psu-User-Agent": cfg.psu_user_agent,
            "Psu-Referer": cfg.psu_referer,
            "Psu-Accept": cfg.psu_accept,
            "Psu-Accept-Charset": cfg.psu_accept_charset,
            "Psu-Accept-Encoding": cfg.psu_accept_encoding,
            "Psu-Accept-Language": cfg.psu_accept_language,
            "Psu-Geo-Location": cfg.psu_geo_location,
        }
        for name, value in optional_headers.items():
            if value:
                headers[name] = value
        return headers

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise RemoteApiError(f"request timed out for {method} {url}") from exc
        except httpx.HTTPError as exc:
            raise RemoteApiError(f"request failed for {method} {url}: {exc}") from exc
        if response.status_code in {401, 403}:
            detail = _error_message(response)
            raise ProviderAuthorizationError(
                f"provider authorization failed for {method} {url}: {response.status_code} {detail}"
            )
        if response.status_code >= 400:
            detail = _error_message(response)
            raise RemoteApiError(
                f"provider request failed for {method} {url}: {response.status_code} {detail}"
            )
        return response.json()

    def list_aspsps(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/aspsps")
        return payload.get("aspsps", [])

    def start_authorization(self, request_body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/auth", json=request_body)

    def authorize_session(self, code: str) -> dict[str, Any]:
        return self._request("POST", "/sessions", json={"code": code})

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}")

    def get_account_balances(self, account_id: str) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{account_id}/balances")

    def get_account_transactions(
        self,
        account_id: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        continuation_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if continuation_key:
            params["continuation_key"] = continuation_key
        return self._request("GET", f"/accounts/{account_id}/transactions", params=params)

    def iter_transactions(
        self,
        account_id: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        continuation_key: str | None = None
        while True:
            page = self.get_account_transactions(
                account_id,
                date_from=date_from,
                date_to=date_to,
                continuation_key=continuation_key,
            )
            yield page
            continuation_key = page.get("continuation_key")
            if not continuation_key:
                break


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    message = payload.get("message") or payload.get("error") or "unknown error"
    detail = payload.get("detail")
    return f"{message}: {detail}" if detail else str(message)


@contextmanager
def enable_client(config: AppConfig, jwt_token: str) -> Iterator[EnableBankingClient]:
    client = EnableBankingClient(config, jwt_token)
    try:
        yield client
    finally:
        client.close()

