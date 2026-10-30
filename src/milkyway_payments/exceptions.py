"""Typed exception hierarchy for the MilkyWay Payments API.

Every error returned by the API surfaces as a :class:`MilkywayApiError` (or a
subclass), carrying the HTTP status code and the server's ``error`` message when
present.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _error_document(body: Optional[str]) -> Dict[str, Any]:
    if not (body and body.strip()):
        return {}
    try:
        doc = json.loads(body)
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _string_member(doc: Dict[str, Any], key: str) -> Optional[str]:
    value = doc.get(key)
    return value if isinstance(value, str) else None


class MilkywayApiError(Exception):
    """Base error for all failures returned by the MilkyWay Payments API.

    Carries the HTTP ``status_code`` (``0`` when the request never completed),
    the raw ``response_body`` for diagnostics, ``error_code`` (the ``error``
    member of a JSON error body verbatim, e.g. ``ErrPaymentRejected``; ``None``
    when the body has none), and, on a field-level 400, the ``field`` at fault by
    its JSON name or path (e.g. ``amount_credit``, ``recipient_id``,
    ``sender_info.date_of_birth``).
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        response_body: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        self.field = field
        self.error_code = _string_member(_error_document(response_body), "error")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.status_code}] {self.message}"


class MilkywayValidationError(MilkywayApiError):
    """HTTP 400 — request validation failed (bad amount, missing field, unresolvable FX rate).

    ``field`` names the request field at fault when the server reports one —
    including ``recipient_id`` when the recipient bank reports the recipient
    invalid (``ErrRecipientInvalid``) and ``currency_credit`` when the currency is
    outside the target's settlement currencies.
    """

    def __init__(
        self,
        message: str,
        response_body: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        super().__init__(400, message, response_body, field)


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


class MilkywayPaymentRejectedError(MilkywayApiError):
    """HTTP 422 — the recipient bank refused the payment on its merits.

    The request was well formed (``error_code`` is ``ErrPaymentRejected``), but
    repeating it will not change the answer, so it is never retried. Nothing was
    created or debited; the bank's own reason is not disclosed. Raised by
    ``precheck`` and ``pay``.
    """

    def __init__(self, message: str, response_body: Optional[str] = None) -> None:
        super().__init__(422, message, response_body)


class MilkywayServiceUnavailableError(MilkywayApiError):
    """HTTP 5xx — the API or a downstream recipient service is unavailable.

    On a 503 the body names the downstream service that failed:
    ``service_id`` and ``third_party_id`` (``None`` when absent).
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        response_body: Optional[str] = None,
    ) -> None:
        super().__init__(status_code, message, response_body)
        doc = _error_document(response_body)
        self.service_id = _string_member(doc, "service_id")
        self.third_party_id = _string_member(doc, "third_party_id")


class MilkywayRecipientBankError(MilkywayServiceUnavailableError):
    """HTTP 502 — the recipient bank's connector failed in a way MilkyWay could not classify.

    ``error_code`` is ``ErrRecipientBankError``. Nothing was created or debited;
    retry later or route the payment through another service. A subclass of
    :class:`MilkywayServiceUnavailableError`, so existing handlers still catch it,
    and retried automatically like any transient 5xx. Raised by ``precheck``,
    ``pay`` and ``cancel``.
    """

    def __init__(self, message: str, response_body: Optional[str] = None) -> None:
        super().__init__(502, message, response_body)
