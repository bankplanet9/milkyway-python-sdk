"""Keycloak client-credentials token provider.

Acquires access tokens via the client-credentials grant and caches them until
shortly before expiry. Concurrent callers share a single in-flight acquisition
(single-flight via a :class:`threading.Lock`) so a burst of requests triggers at
most one token fetch.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import requests

from .exceptions import MilkywayAuthError
from .models import MilkywayOptions


class KeycloakTokenProvider:
    """Acquires and caches Keycloak client-credentials tokens."""

    def __init__(
        self,
        options: MilkywayOptions,
        session: Optional[requests.Session] = None,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._options = options
        # A plain session for the token endpoint only — it must NOT route through
        # the SDK's auth/retry pipeline, to avoid recursion.
        self._session = session if session is not None else requests.Session()
        self._time = time_fn
        self._lock = threading.Lock()
        self._cached_token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Return a valid bearer token, acquiring or refreshing as needed."""
        if not force_refresh:
            cached = self._try_get_cached()
            if cached is not None:
                return cached

        with self._lock:
            # Re-check under the lock: another caller may have refreshed while we
            # waited.
            if not force_refresh:
                cached = self._try_get_cached()
                if cached is not None:
                    return cached
            return self._acquire()

    def _try_get_cached(self) -> Optional[str]:
        if (
            self._cached_token is not None
            and self._time() < self._expires_at - self._options.token_refresh_skew
        ):
            return self._cached_token
        return None

    def _acquire(self) -> str:
        form = {
            "grant_type": "client_credentials",
            "client_id": self._options.client_id,
            "client_secret": self._options.client_secret,
        }
        if self._options.scope and self._options.scope.strip():
            form["scope"] = self._options.scope

        try:
            response = self._session.post(
                self._options.token_url,
                data=form,
                timeout=self._options.request_timeout,
            )
        except requests.RequestException as ex:
            raise MilkywayAuthError(
                "Failed to reach the Keycloak token endpoint."
            ) from ex

        body = response.text
        if not response.ok:
            raise MilkywayAuthError(
                f"Token acquisition failed with status {response.status_code}.",
                body,
            )

        try:
            parsed = response.json()
        except ValueError as ex:
            raise MilkywayAuthError(
                "Token endpoint returned a malformed response.", body
            ) from ex

        access_token = parsed.get("access_token") if isinstance(parsed, dict) else None
        if not access_token:
            raise MilkywayAuthError(
                "Token endpoint response contained no access_token.", body
            )

        expires_in = 0
        if isinstance(parsed, dict):
            try:
                expires_in = int(parsed.get("expires_in", 0))
            except (TypeError, ValueError):
                expires_in = 0

        self._cached_token = access_token
        self._expires_at = self._time() + expires_in
        return access_token
