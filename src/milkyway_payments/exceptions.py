"""Typed exception hierarchy for the MilkyWay Payments API.

Every error returned by the API surfaces as a :class:`MilkywayApiError` (or a
subclass), carrying the HTTP status code and the server's ``error`` message when
present.
"""

from __future__ import annotations

from typing import Optional


class MilkywayApiError(Exception):
    """Base error for all failures returned by the MilkyWay Payments API.

    Carries the HTTP ``status_code`` (``0`` when the request never completed) and
    the raw ``response_body`` for diagnostics.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        response_body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.response_body = response_body

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.status_code}] {self.message}"


class MilkywayValidationError(MilkywayApiError):
    """HTTP 400 — request validation failed (bad amount, missing field, unresolvable FX rate)."""

    def __init__(self, message: str, response_body: Optional[str] = None) -> None:
        super().__init__(400, message, response_body)


class MilkywayAuthError(MilkywayApiError):
    """HTTP 401 — missing, malformed, or invalid token (incl. failed token acquisition)."""

    def __init__(self, message: str, response_body: Optional[str] = None) -> None:
        super().__init__(401, message, response_body)


class MilkywayExposureBlockedError(MilkywayApiError):
    """HTTP 402 — payment would breach a block-action exposure limit."""

    def __init__(self, message: str, response_body: Optional[str] = None) -> None:
        super().__init__(402, message, response_body)


class MilkywayNotFoundError(MilkywayApiError):
    """HTTP 404 — transaction not found, or not owned by your institution."""

    def __init__(self, message: str, response_body: Optional[str] = None) -> None:
        super().__init__(404, message, response_body)


class MilkywayServiceUnavailableError(MilkywayApiError):
    """HTTP 5xx — the API or a downstream recipient service is unavailable."""

    def __init__(
        self,
        status_code: int,
        message: str,
        response_body: Optional[str] = None,
    ) -> None:
        super().__init__(status_code, message, response_body)
