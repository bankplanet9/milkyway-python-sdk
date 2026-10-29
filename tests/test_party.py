from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
import responses

from milkyway_payments import (
    IdentityDocumentType,
    MilkywayPaymentsClient,
    MilkywayValidationError,
    PartyAddress,
    PartyFieldPath,
    PartyInfo,
    PartyName,
    PartyProfile,
    PartyRequirements,
    PartyType,
    PayRequest,
    PrecheckRequest,
)

from conftest import BASE_URL, TOKEN_URL


def _client(options, token_body) -> MilkywayPaymentsClient:
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    return MilkywayPaymentsClient(options)


def _precheck_request(**parties) -> PrecheckRequest:
    return PrecheckRequest(
        third_party_id_debit="bank-beta",
        service_id="card",
        recipient_id="r-1",
        amount_credit=Decimal("100"),
        currency_credit="USD",
        **parties,
    )


def _raw_body() -> str:
    body = responses.calls[-1].request.body
    return body.decode() if isinstance(body, bytes) else body


_FULL_SENDER = PartyInfo(
    party_type=PartyType.NATURAL,
    name=PartyName(first="Ivan", last="Petrov", full="Petrov Ivan Sergeevich"),
    date_of_birth=date(1990, 4, 18),
    identity_document_type=IdentityDocumentType.PASSPORT,
    identity_document_number="AB1234567",
    identity_document_country="TJ",
    country_of_residence="AE",
    address=PartyAddress(
        country="AE",
        city="Dubai",
        street="Sheikh Zayed Rd",
        building="12",
        postal_code="00000",
        line=["Office 4"],
    ),
)

_FULL_SENDER_WIRE = (
    '{"party_type": "natural", "name": {"first": "Ivan", "last": "Petrov", "full": "Petrov Ivan Sergeevich"}, '
    '"date_of_birth": "1990-04-18", "identity_document_type": "passport", "identity_document_number": "AB1234567", '
    '"identity_document_country": "TJ", "country_of_residence": "AE", '
    '"address": {"country": "AE", "city": "Dubai", "street": "Sheikh Zayed Rd", "building": "12", '
    '"postal_code": "00000", "line": ["Office 4"]}}'
)


@responses.activate
def test_precheck_serializes_parties_with_exact_keys(options, token_body):
    client = _client(options, token_body)
    responses.add(responses.POST, f"{BASE_URL}/payments/v1/precheck", json={}, status=200)

    client.precheck(
        _precheck_request(
            sender_info=_FULL_SENDER,
            recipient_info=PartyInfo(party_type="natural", name=PartyName(full="Karimov Ali")),
        )
    )

    sent = json.loads(_raw_body())
    assert json.dumps(sent["sender_info"]) == _FULL_SENDER_WIRE
    assert sent["recipient_info"] == {"party_type": "natural", "name": {"full": "Karimov Ali"}}
    assert "data" not in sent


@responses.activate
def test_pay_serializes_parties(options, token_body):
    client = _client(options, token_body)
    responses.add(responses.POST, f"{BASE_URL}/payments/v1", json={"transaction_id": 1}, status=200)

    client.pay(
        PayRequest(
            third_party_id_debit="bank-beta",
            service_id="card",
            sender_id="s-1",
            recipient_id="r-1",
            amount_credit=Decimal("100"),
            currency_credit="USD",
            sender_info=PartyInfo(
                party_type=PartyType.NATURAL,
                identity_document_type="national_id",
                identity_document_number="123",
            ),
            recipient_info=PartyInfo(party_type=PartyType.NATURAL, country_of_residence="TJ"),
        ),
        idempotency_key="k",
    )

    raw = _raw_body()
    assert (
        '"sender_info": {"party_type": "natural", "identity_document_type": "national_id", '
        '"identity_document_number": "123"}'
    ) in raw
    assert '"recipient_info": {"party_type": "natural", "country_of_residence": "TJ"}' in raw


@pytest.mark.parametrize(
    "party, expected",
    [
        (PartyInfo(party_type=PartyType.NATURAL), {"party_type": "natural"}),
        (
            PartyInfo(
                party_type=PartyType.NATURAL,
                name=PartyName(first="", last=None),
                date_of_birth="",
                address=PartyAddress(country="", line=[]),
            ),
            {"party_type": "natural"},
        ),
        (
            PartyInfo(party_type=PartyType.NATURAL, name=PartyName(last="Petrov")),
            {"party_type": "natural", "name": {"last": "Petrov"}},
        ),
        (
            PartyInfo(party_type=PartyType.NATURAL, address=PartyAddress(country="TJ")),
            {"party_type": "natural", "address": {"country": "TJ"}},
        ),
        (
            PartyInfo(party_type=PartyType.NATURAL, date_of_birth="1990-04-18"),
            {"party_type": "natural", "date_of_birth": "1990-04-18"},
        ),
    ],
)
def test_party_info_omits_empty_fields(party, expected):
    assert party.to_payload() == expected


@responses.activate
def test_parties_omitted_when_not_supplied(options, token_body):
    client = _client(options, token_body)
    responses.add(responses.POST, f"{BASE_URL}/payments/v1/precheck", json={}, status=200)

    client.precheck(_precheck_request())

    sent = json.loads(_raw_body())
    assert "sender_info" not in sent
    assert "recipient_info" not in sent


@responses.activate
def test_validation_error_exposes_field(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/precheck",
        json={
            "error": "sender_info.date_of_birth: is required by the receiving bank for this service",
            "field": "sender_info.date_of_birth",
        },
        status=400,
    )

    with pytest.raises(MilkywayValidationError) as info:
        client.precheck(_precheck_request())

    assert info.value.field == "sender_info.date_of_birth"
    assert info.value.message.startswith("sender_info.date_of_birth: is required")


@responses.activate
def test_discovery_decodes_party_profile(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/discovery",
        json={
            "destinations": [
                {
                    "third_party_id": "bank-beta",
                    "services": [
                        {
                            "service_id": "card",
                            "payout_method": "card",
                            "party_profile": {
                                "sender_info": {
                                    "required": [
                                        "name.first",
                                        "name.last",
                                        "date_of_birth",
                                        "identity_document_type",
                                        "identity_document_number",
                                    ],
                                    "accepted": ["name.full"],
                                    "identity_document_types": ["passport"],
                                },
                                "recipient_info": {"accepted": ["address.line"]},
                            },
                        },
                        {"service_id": "wallet", "payout_method": "wallet"},
                    ],
                }
            ]
        },
        status=200,
    )

    [dest] = client.discovery()
    card, wallet = dest.services

    assert card.party_profile == PartyProfile(
        sender_info=PartyRequirements(
            required=[
                "name.first",
                "name.last",
                "date_of_birth",
                "identity_document_type",
                "identity_document_number",
            ],
            accepted=["name.full"],
            identity_document_types=["passport"],
        ),
        recipient_info=PartyRequirements(accepted=["address.line"]),
    )
    assert PartyFieldPath.DATE_OF_BIRTH in card.party_profile.sender_info.required
    assert IdentityDocumentType.PASSPORT in card.party_profile.sender_info.identity_document_types
    assert card.party_profile.recipient_info.required == []
    assert wallet.party_profile is None
