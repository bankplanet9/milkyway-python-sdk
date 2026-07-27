from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import responses

from milkyway_payments import (
    Destination,
    MilkywayNotFoundError,
    MilkywayPaymentsClient,
    ServiceCapability,
)

from conftest import BASE_URL, TOKEN_URL


def _client(options, token_body) -> MilkywayPaymentsClient:
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    return MilkywayPaymentsClient(options)


_DESTINATIONS_BODY = {
    "destinations": [
        {
            "third_party_id": "bank-beta",
            "partner_name": "Bank Beta",
            "country": "TJ",
            "services": [
                {
                    "service_id": "card-payout",
                    "payout_method": "card",
                    "recipient": "recipient-9999",
                    "payout_currencies": ["USD", "TJS"],
                },
                {
                    "service_id": "wallet-payout",
                    "payout_method": "wallet",
                },
            ],
        }
    ]
}


@responses.activate
def test_discovery_without_country_omits_query(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/discovery",
        json=_DESTINATIONS_BODY,
        status=200,
    )

    destinations = client.discovery()

    assert len(destinations) == 1
    dest = destinations[0]
    assert isinstance(dest, Destination)
    assert dest.third_party_id == "bank-beta"
    assert dest.partner_name == "Bank Beta"
    assert dest.country == "TJ"
    assert len(dest.services) == 2
    assert isinstance(dest.services[0], ServiceCapability)
    assert dest.services[0].service_id == "card-payout"
    assert dest.services[0].payout_method == "card"
    assert dest.services[0].payout_currencies == ["USD", "TJS"]
    # optional fields absent on the wire default cleanly
    assert dest.services[1].recipient is None
    assert dest.services[1].payout_currencies is None

    call = [c for c in responses.calls if "discovery" in c.request.url][0]
    assert urlparse(call.request.url).query == ""
    assert call.request.headers["Authorization"] == "Bearer tok-1"


@responses.activate
def test_discovery_with_country_sends_query(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/discovery",
        json={"destinations": []},
        status=200,
    )

    assert client.discovery(country="tj") == []

    call = [c for c in responses.calls if "discovery" in c.request.url][0]
    assert parse_qs(urlparse(call.request.url).query) == {"country": ["tj"]}


@responses.activate
def test_service_schema_returns_raw_dict(options, token_body):
    client = _client(options, token_body)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["passport"],
        "properties": {"passport": {"type": "string"}},
    }
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/discovery/bank-beta/card-payout/schema",
        json=schema,
        status=200,
    )

    result = client.service_schema("bank-beta", "card-payout")

    assert result == schema
    call = [c for c in responses.calls if "discovery" in c.request.url][0]
    assert urlparse(call.request.url).path == "/payments/v1/discovery/bank-beta/card-payout/schema"


@responses.activate
def test_service_schema_url_encodes_path_segments(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/discovery/bank%2Fbeta/card%20payout/schema",
        json={"type": "object"},
        status=200,
    )

    client.service_schema("bank/beta", "card payout")

    call = [c for c in responses.calls if "discovery" in c.request.url][0]
    assert "bank%2Fbeta" in call.request.url
    assert "card%20payout" in call.request.url


@responses.activate
def test_service_schema_maps_404(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/discovery/bank-beta/nope/schema",
        json={"error": "unknown service"},
        status=404,
    )

    try:
        client.service_schema("bank-beta", "nope")
        assert False, "expected MilkywayNotFoundError"
    except MilkywayNotFoundError as ex:
        assert ex.status_code == 404
        assert ex.message == "unknown service"
