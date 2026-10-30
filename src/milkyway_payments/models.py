"""Typed request/response models and the transaction-status enum.

Money fields use :class:`decimal.Decimal` so the API's JSON numbers bind
losslessly (the client parses responses with ``parse_float=Decimal``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum, IntEnum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union


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


class PartyType(str, Enum):
    """The kind of payment party in a :class:`PartyInfo`.

    Use :attr:`NATURAL` (a person). :attr:`LEGAL` is part of the model, but the
    API refuses it (400) for now.
    """

    NATURAL = "natural"
    LEGAL = "legal"


class IdentityDocumentType(str, Enum):
    """The kind of identity document in a :class:`PartyInfo`.

    The vocabulary is closed and maps one-to-one to IVMS101
    ``nationalIdentifierType``: passport (CCPT), national_id (IDCD),
    driver_license (DRLC), residence_permit (ARNU), tax_id (TXID),
    social_security (SOCS), other (MISC).
    """

    PASSPORT = "passport"
    NATIONAL_ID = "national_id"
    DRIVER_LICENSE = "driver_license"
    RESIDENCE_PERMIT = "residence_permit"
    TAX_ID = "tax_id"
    SOCIAL_SECURITY = "social_security"
    OTHER = "other"


class PartyFieldPath(str, Enum):
    """A field of a :class:`PartyInfo`, as listed in :class:`PartyRequirements`."""

    NAME_FIRST = "name.first"
    NAME_LAST = "name.last"
    NAME_FULL = "name.full"
    DATE_OF_BIRTH = "date_of_birth"
    IDENTITY_DOCUMENT_TYPE = "identity_document_type"
    IDENTITY_DOCUMENT_NUMBER = "identity_document_number"
    IDENTITY_DOCUMENT_COUNTRY = "identity_document_country"
    COUNTRY_OF_RESIDENCE = "country_of_residence"
    ADDRESS_COUNTRY = "address.country"
    ADDRESS_CITY = "address.city"
    ADDRESS_STREET = "address.street"
    ADDRESS_BUILDING = "address.building"
    ADDRESS_POSTAL_CODE = "address.postal_code"
    ADDRESS_LINE = "address.line"


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values (``None``, ``""``, empty lists and dicts) from a payload."""
    return {k: v for k, v in payload.items() if v is not None and v != "" and v != [] and v != {}}


def _wire_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value


@dataclass
class PartyName:
    """The name of a payment party.

    ``full`` is the name as written in the identity document: family name
    first, with a patronymic if any (e.g. ``Petrov Ivan Sergeevich``).
    """

    first: Optional[str] = None
    last: Optional[str] = None
    full: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return _compact({"first": self.first, "last": self.last, "full": self.full})


@dataclass
class PartyAddress:
    """The address of a payment party.

    ``country`` (ISO 3166-1 alpha-2, upper case) is required when an address is
    sent; ``line`` holds an address kept as free text, one line per element (at
    most 7).
    """

    country: str
    city: Optional[str] = None
    street: Optional[str] = None
    building: Optional[str] = None
    postal_code: Optional[str] = None
    line: Optional[Sequence[str]] = None

    def to_payload(self) -> Dict[str, Any]:
        return _compact(
            {
                "country": self.country,
                "city": self.city,
                "street": self.street,
                "building": self.building,
                "postal_code": self.postal_code,
                "line": list(self.line) if self.line is not None else None,
            }
        )


@dataclass
class PartyInfo:
    """The canonical identity of a payment party.

    Used for the payer (``sender_info``) and the beneficiary
    (``recipient_info``). The model is IVMS101-anchored and the same for every
    recipient bank and service; each bank's connector converts it to the bank's
    own format. The account, card or phone stays in ``sender_id`` /
    ``recipient_id``.

    Only ``party_type`` is required. Empty fields, and an empty ``name`` or
    ``address``, are left out of the request. ``date_of_birth`` is an ISO 8601
    ``YYYY-MM-DD`` string or a :class:`datetime.date`;
    ``identity_document_type`` is required with ``identity_document_number``
    (series and number together, as in the document); the countries are ISO
    3166-1 alpha-2, upper case. Text values are at most 256 characters.

    Which fields a service needs is published in its
    :attr:`ServiceCapability.party_profile`; a missing required field or an
    invalid value raises :class:`MilkywayValidationError` whose ``field`` names
    it (e.g. ``sender_info.date_of_birth``).
    """

    party_type: Union[PartyType, str]
    name: Optional[PartyName] = None
    date_of_birth: Optional[Union[date, str]] = None
    identity_document_type: Optional[Union[IdentityDocumentType, str]] = None
    identity_document_number: Optional[str] = None
    identity_document_country: Optional[str] = None
    country_of_residence: Optional[str] = None
    address: Optional[PartyAddress] = None

    def to_payload(self) -> Dict[str, Any]:
        return _compact(
            {
                "party_type": _wire_value(self.party_type),
                "name": self.name.to_payload() if self.name is not None else None,
                "date_of_birth": _wire_value(self.date_of_birth),
                "identity_document_type": _wire_value(self.identity_document_type),
                "identity_document_number": self.identity_document_number,
                "identity_document_country": self.identity_document_country,
                "country_of_residence": self.country_of_residence,
                "address": self.address.to_payload() if self.address is not None else None,
            }
        )


@dataclass
class PartyRequirements:
    """The field paths a recipient bank uses within one party object.

    ``required`` fields must be sent (a missing one is refused with 400 naming
    it); ``accepted`` fields are used when present; a field in neither list is
    not used by the bank. ``identity_document_types`` lists the document kinds
    the bank takes — empty means any. Values are the wire strings, which compare
    equal to :class:`PartyFieldPath` / :class:`IdentityDocumentType` members.
    """

    required: List[str] = field(default_factory=list)
    accepted: List[str] = field(default_factory=list)
    identity_document_types: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "PartyRequirements":
        return cls(
            required=list(body.get("required") or []),
            accepted=list(body.get("accepted") or []),
            identity_document_types=list(body.get("identity_document_types") or []),
        )


@dataclass
class PartyProfile:
    """Which :class:`PartyInfo` fields a service's recipient bank requires and accepts.

    The same profile the bank enforces at precheck and pay. A side that is
    ``None`` needs no fields.
    """

    sender_info: Optional[PartyRequirements] = None
    recipient_info: Optional[PartyRequirements] = None

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "PartyProfile":
        sender = body.get("sender_info")
        recipient = body.get("recipient_info")
        return cls(
            sender_info=PartyRequirements.from_dict(sender) if sender is not None else None,
            recipient_info=(
                PartyRequirements.from_dict(recipient) if recipient is not None else None
            ),
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

    ``sender_info`` is your customer, the payer; ``recipient_info`` is the
    beneficiary. The fields the service requires are in its discovery
    ``party_profile``. ``data`` carries only a service's non-identity extras
    (see :meth:`MilkywayPaymentsClient.service_schema`) — most services take
    none; never put the payer's or beneficiary's identity in it.
    """

    third_party_id_debit: str
    service_id: str
    recipient_id: str
    amount_credit: Decimal
    currency_credit: str
    data: Optional[Mapping[str, Any]] = None
    sender_info: Optional[PartyInfo] = None
    recipient_info: Optional[PartyInfo] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "third_party_id_debit": self.third_party_id_debit,
            "service_id": self.service_id,
            "recipient_id": self.recipient_id,
            "amount_credit": self.amount_credit,
            "currency_credit": self.currency_credit,
        }
        if self.sender_info is not None:
            payload["sender_info"] = self.sender_info.to_payload()
        if self.recipient_info is not None:
            payload["recipient_info"] = self.recipient_info.to_payload()
        if self.data is not None:
            payload["data"] = dict(self.data)
        return payload


@dataclass
class PayRequest:
    """Request to initiate a cross-bank payment.

    The credit party (your institution) is resolved from the access token's
    ``azp`` claim — do not send ``third_party_id_credit``.

    ``sender_info`` is your customer, the payer; ``recipient_info`` is the
    beneficiary. The fields the service requires are in its discovery
    ``party_profile``. ``data`` carries only a service's non-identity extras
    (see :meth:`MilkywayPaymentsClient.service_schema`) — most services take
    none; never put the payer's or beneficiary's identity in it.
    """

    third_party_id_debit: str
    service_id: str
    sender_id: str
    recipient_id: str
    amount_credit: Decimal
    currency_credit: str
    data: Optional[Mapping[str, Any]] = None
    sender_info: Optional[PartyInfo] = None
    recipient_info: Optional[PartyInfo] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "third_party_id_debit": self.third_party_id_debit,
            "service_id": self.service_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "amount_credit": self.amount_credit,
            "currency_credit": self.currency_credit,
        }
        if self.sender_info is not None:
            payload["sender_info"] = self.sender_info.to_payload()
        if self.recipient_info is not None:
            payload["recipient_info"] = self.recipient_info.to_payload()
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

    ``payout_currencies`` lists the currencies the service can pay out in;
    ``party_profile`` says which ``sender_info`` / ``recipient_info`` fields the
    recipient bank requires and accepts (``None`` when the bank has published
    none). The JSON Schema of the service's non-identity ``data`` extras is not
    included in the discovery listing — fetch it with
    :meth:`MilkywayPaymentsClient.service_schema`.
    """

    service_id: str
    payout_method: str
    recipient: Optional[str] = None
    payout_currencies: Optional[list] = None
    party_profile: Optional[PartyProfile] = None

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> "ServiceCapability":
        currencies = body.get("payout_currencies")
        profile = body.get("party_profile")
        return cls(
            service_id=body.get("service_id", ""),
            payout_method=body.get("payout_method", ""),
            recipient=body.get("recipient"),
            payout_currencies=list(currencies) if currencies is not None else None,
            party_profile=PartyProfile.from_dict(profile) if profile is not None else None,
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
