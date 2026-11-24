from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from .config import api_url


class BytePlusError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    data: dict
    request_id: str
    provider_log_id: str | None


class BytePlusClient:
    def __init__(
        self,
        api_key: str,
        endpoint: str | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint or api_url()
        self._timeout = timeout_seconds

    def create(self, payload: dict, request_id: str | None = None) -> ProviderResult:
        return self._create(payload, request_id=request_id, on_request_start=None)

    def create_observed(
        self,
        payload: dict,
        *,
        on_request_start: Callable[[str], None],
        on_response_received: Callable[[str | None], None],
    ) -> ProviderResult:
        """Create while exposing the real request ID immediately before the call."""
        return self._create(
            payload,
            request_id=None,
            on_request_start=on_request_start,
            on_response_received=on_response_received,
        )

    def _create(
        self,
        payload: dict,
        *,
        request_id: str | None,
        on_request_start: Callable[[str], None] | None,
        on_response_received: Callable[[str | None], None] | None = None,
    ) -> ProviderResult:
        request_id = request_id or str(uuid.uuid4())
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self._api_key,
            "X-Api-Request-Id": request_id,
        }
        if on_request_start is not None:
            on_request_start(request_id)

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(self._endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise BytePlusError(f"BytePlus request failed: {exc}") from exc

        provider_log_id = response.headers.get("X-Tt-Logid") or response.headers.get(
            "x-tt-logid"
        )
        if on_response_received is not None:
            on_response_received(provider_log_id)

        try:
            data = response.json()
        except ValueError as exc:
            raise BytePlusError(
                f"BytePlus returned HTTP {response.status_code} with non-JSON content"
            ) from exc

        if response.status_code >= 400:
            message = data.get("message") if isinstance(data, dict) else None
            raise BytePlusError(
                f"BytePlus HTTP {response.status_code}: {message or data}"
            )

        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise BytePlusError(
                f"BytePlus business error {data.get('code')}: {data.get('message', '')}"
            )

        return ProviderResult(
            data=data,
            request_id=request_id,
            provider_log_id=provider_log_id,
        )
