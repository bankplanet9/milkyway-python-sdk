"""Typed request/response models and the transaction-status enum.

Money fields use :class:`decimal.Decimal` so the API's JSON numbers bind
losslessly (the client parses responses with ``parse_float=Decimal``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum
from typing import Any, Dict, Mapping, Optional


class TransactionStatus(IntEnum):
    """Lifecycle status of a payment transaction (integer codes from the API)."""

    PENDING = 0
    DONE = 1
    CANCELLED = 2
    FAILED = 3
    CANCEL_PENDING = 4
    STUCK = 5

    def is_terminal(self) -> bool:
        """True when the status will not change without external action.

        Terminal statuses are :attr:`DONE`, :attr:`CANCELLED`, :attr:`FAILED`,
        and :attr:`STUCK`. Polling should stop once one is reached.
        """
        return self in (
            TransactionStatus.DONE,
            TransactionStatus.CANCELLED,
            TransactionStatus.FAILED,
            TransactionStatus.STUCK,
        )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    # Strings and ints are exact; a stray float is routed through str() to avoid
    # binary-float drift.
    return Decimal(str(value))


@dataclass
class PrecheckRequest:
    """Request for a payment quote (rate + commission) without creating a payment.

    The credit party (your institution) is resolved from the access token's
    ``azp`` claim and must not be sent here.
    """

    third_party_id_debit: str
    service_id: str
    recipient_id: str
    amount_credit: Decimal
    currency_credit: str
    data: Optional[Mapping[str, Any]] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "third_party_id_debit": self.third_party_id_debit,
            "service_id": self.service_id,
            "recipient_id": self.recipient_id,
            "amount_credit": self.amount_credit,
            "currency_credit": self.currency_credit,
        }
        if self.data is not None:
            payload["data"] = dict(self.data)
        return payload


@dataclass
class PayRequest:
    """Request to initiate a cross-bank payment.

    The credit party (your institution) is resolved from the access token's
    ``azp`` claim — do not send ``third_party_id_credit``.
    """

    third_party_id_debit: str
    service_id: str
    sender_id: str
    recipient_id: str
    amount_credit: Decimal
    currency_credit: str
    data: Optional[Mapping[str, Any]] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "third_party_id_debit": self.third_party_id_debit,
            "service_id": self.service_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "amount_credit": self.amount_credit,
            "currency_credit": self.currency_credit,
        }
        if self.data is not None:
            payload["data"] = dict(self.data)
        return payload


@dataclass
class PrecheckResult:
    """Quote for a prospective payment; the FX markup is already applied."""

    third_party_id: Optional[str]
    service_id: Optional[str]
    recipient_id: Optional[str]
    amount_credit: Decimal
    currency_credit: Optional[str]
    amount_debit: Decimal
    currency_debit: Optional[str]
    rate: Decimal
    commission: Decimal

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "PrecheckResult":
        return cls(
            third_party_id=body.get("third_party_id"),
            service_id=body.get("service_id"),
            recipient_id=body.get("recipient_id"),
            amount_credit=_to_decimal(body.get("amount_credit")),
            currency_credit=body.get("currency_credit"),
            amount_debit=_to_decimal(body.get("amount_debit")),
            currency_debit=body.get("currency_debit"),
            rate=_to_decimal(body.get("rate")),
            commission=_to_decimal(body.get("commission")),
        )


@dataclass
class PostcheckResult:
    """Current status of a payment transaction."""

    transaction_id: int
    status: TransactionStatus
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "PostcheckResult":
        return cls(
            transaction_id=int(body.get("transaction_id", 0)),
            status=TransactionStatus(int(body.get("status", 0))),
            error=body.get("error"),
        )


@dataclass
class CancelResult:
    """Result of a cancellation request: the resulting transaction status."""

    status: TransactionStatus

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "CancelResult":
        return cls(status=TransactionStatus(int(body.get("status", 0))))


@dataclass
class ServiceCapability:
    """A payout capability a destination exposes for one service.

    ``payout_currencies`` lists the currencies the service can pay out in; the
    per-service ``data`` JSON Schema is not included in the discovery listing —
    fetch it with :meth:`MilkywayPaymentsClient.service_schema`.
    """

    service_id: str
    payout_method: str
    recipient: Optional[str] = None
    payout_currencies: Optional[list] = None

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "ServiceCapability":
        currencies = body.get("payout_currencies")
        return cls(
            service_id=body.get("service_id", ""),
            payout_method=body.get("payout_method", ""),
            recipient=body.get("recipient"),
            payout_currencies=list(currencies) if currencies is not None else None,
        )


@dataclass
class Destination:
    """A reachable counterparty and the services it can be paid through."""

    third_party_id: str
    partner_name: Optional[str] = None
    country: Optional[str] = None
    services: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "Destination":
        return cls(
            third_party_id=body.get("third_party_id", ""),
            partner_name=body.get("partner_name"),
            country=body.get("country"),
            services=[
                ServiceCapability.from_dict(s) for s in body.get("services") or []
            ],
        )


@dataclass
class PollOptions:
    """Controls :meth:`MilkywayPaymentsClient.wait_for_completion` polling."""

    initial_delay: float = 1.0
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    timeout: float = 300.0


@dataclass
class MilkywayOptions:
    """Configuration for :class:`MilkywayPaymentsClient`.

    Holds the API endpoint, Keycloak client-credentials, and resilience tuning.
    """

    base_url: str
    token_url: str
    client_id: str
    client_secret: str
    scope: Optional[str] = None
    token_refresh_skew: float = 30.0
    request_timeout: float = 30.0
    max_retries: int = 3
    retry_base_delay: float = 0.5

    def validate(self) -> None:
        if not (self.base_url and self.base_url.strip()):
            raise ValueError("base_url is required.")
        if not (self.token_url and self.token_url.strip()):
            raise ValueError("token_url is required.")
        if not (self.client_id and self.client_id.strip()):
            raise ValueError("client_id is required.")
        if not (self.client_secret and self.client_secret.strip()):
            raise ValueError("client_secret is required.")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
