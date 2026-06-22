"""MilkyWay Payments SDK for Python.

Official client for the MilkyWay Payments API (``/payments/v1``) — the
partner-facing API banks use to initiate, quote, track, and cancel cross-bank
payments.
"""

from __future__ import annotations

from .auth import KeycloakTokenProvider
from .client import MilkywayPaymentsClient
from .exceptions import (
    MilkywayApiError,
    MilkywayAuthError,
    MilkywayExposureBlockedError,
    MilkywayNotFoundError,
    MilkywayServiceUnavailableError,
    MilkywayValidationError,
)
from .models import (
    CancelResult,
    MilkywayOptions,
    PayRequest,
    PollOptions,
    PostcheckResult,
    PrecheckRequest,
    PrecheckResult,
    TransactionStatus,
)

__all__ = [
    "MilkywayPaymentsClient",
    "MilkywayOptions",
    "KeycloakTokenProvider",
    "TransactionStatus",
    "PrecheckRequest",
    "PrecheckResult",
    "PayRequest",
    "PostcheckResult",
    "CancelResult",
    "PollOptions",
    "MilkywayApiError",
    "MilkywayValidationError",
    "MilkywayAuthError",
    "MilkywayExposureBlockedError",
    "MilkywayNotFoundError",
    "MilkywayServiceUnavailableError",
]

__version__ = "0.0.0"
