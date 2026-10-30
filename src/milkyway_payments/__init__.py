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
    MilkywayPaymentRejectedError,
    MilkywayRecipientBankError,
    MilkywayServiceUnavailableError,
    MilkywayValidationError,
)
from .models import (
    CancelResult,
    Destination,
    IdentityDocumentType,
    MilkywayOptions,
    PartyAddress,
    PartyFieldPath,
    PartyInfo,
    PartyName,
    PartyProfile,
    PartyRequirements,
    PartyType,
    PayRequest,
    PollOptions,
    PostcheckResult,
    PrecheckRequest,
    PrecheckResult,
    ServiceCapability,
    StatusReason,
    TransactionStatus,
)

__all__ = [
    "MilkywayPaymentsClient",
    "MilkywayOptions",
    "KeycloakTokenProvider",
    "TransactionStatus",
    "StatusReason",
    "PrecheckRequest",
    "PrecheckResult",
    "PayRequest",
    "PostcheckResult",
    "CancelResult",
    "Destination",
    "ServiceCapability",
    "PartyInfo",
    "PartyName",
    "PartyAddress",
    "PartyType",
    "IdentityDocumentType",
    "PartyFieldPath",
    "PartyProfile",
    "PartyRequirements",
    "PollOptions",
    "MilkywayApiError",
    "MilkywayValidationError",
    "MilkywayAuthError",
    "MilkywayExposureBlockedError",
    "MilkywayNotFoundError",
    "MilkywayPaymentRejectedError",
    "MilkywayServiceUnavailableError",
    "MilkywayRecipientBankError",
]

__version__ = "0.0.0"
