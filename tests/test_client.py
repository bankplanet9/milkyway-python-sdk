from __future__ import annotations

import json
from decimal import Decimal

import responses

from milkyway_payments import (
    MilkywayAuthError,
    MilkywayExposureBlockedError,
    MilkywayNotFoundError,
    MilkywayPaymentsClient,
    MilkywayServiceUnavailableError,
    MilkywayValidationError,
    PayRequest,
    PrecheckRequest,
    TransactionStatus,
)

from conftest import BASE_URL, TOKEN_URL


def _client(options, token_body) -> MilkywayPaymentsClient:
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    return MilkywayPaymentsClient(options)


@responses.activate
def test_healthcheck_returns_plain_text(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/healthcheck",
        body="OK",
        status=200,
        content_type="text/plain",
    )
    assert client.healthcheck("bank-beta", "card-payout") == "OK"
    # auth header attached
    hc_call = [c for c in responses.calls if "healthcheck" in c.request.url][0]
    assert hc_call.request.headers["Authorization"] == "Bearer tok-1"


@responses.activate
def test_precheck_parses_decimals_exactly(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/precheck",
        # values chosen to break under binary float
        body=json.dumps(
            {
                "third_party_id": "bank-beta",
                "service_id": "card-payout",
                "recipient_id": "r1",
                "amount_credit": 100.10,
                "currency_credit": "USD",
                "amount_debit": 367.30,
                "currency_debit": "AED",
                "rate": 3.6729,
                "commission": 1.15,
            }
        ),
        status=200,
        content_type="application/json",
    )
    result = client.precheck(
        PrecheckRequest(
            third_party_id_debit="bank-beta",
            service_id="card-payout",
            recipient_id="r1",
            amount_credit=Decimal("100.10"),
            currency_credit="USD",
        )
    )
    assert result.amount_debit == Decimal("367.30")
    assert result.rate == Decimal("3.6729")
    assert result.commission == Decimal("1.15")
    assert isinstance(result.amount_debit, Decimal)


@responses.activate
def test_precheck_sends_decimal_as_json_number(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/precheck",
        json={"amount_debit": 1, "rate": 1, "commission": 0, "amount_credit": 1},
        status=200,
    )
    client.precheck(
        PrecheckRequest(
            third_party_id_debit="b",
            service_id="s",
            recipient_id="r",
            amount_credit=Decimal("100.10"),
            currency_credit="USD",
        )
    )
    sent = json.loads(responses.calls[-1].request.body)
    # number, not string, and exact
    assert sent["amount_credit"] == 100.10
    raw = responses.calls[-1].request.body.decode() if isinstance(
        responses.calls[-1].request.body, bytes
    ) else responses.calls[-1].request.body
    assert '"amount_credit": 100.10' in raw or '"amount_credit":100.10' in raw


@responses.activate
def test_pay_with_idempotency_key_sends_header(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1",
        json={"transaction_id": 4242},
        status=200,
    )
    tx = client.pay(
        PayRequest(
            third_party_id_debit="b",
            service_id="s",
            sender_id="snd",
            recipient_id="r",
            amount_credit=Decimal("100"),
            currency_credit="USD",
        ),
        idempotency_key="idem-123",
    )
    assert tx == 4242
    pay_call = [c for c in responses.calls if c.request.url.endswith("/payments/v1")][-1]
    assert pay_call.request.headers["Idempotency-Key"] == "idem-123"


@responses.activate
def test_pay_omits_data_when_none(options, token_body):
    client = _client(options, token_body)
    responses.add(responses.POST, f"{BASE_URL}/payments/v1", json={"transaction_id": 1}, status=200)
    client.pay(
        PayRequest(
            third_party_id_debit="b",
            service_id="s",
            sender_id="snd",
            recipient_id="r",
            amount_credit=Decimal("1"),
            currency_credit="USD",
        )
    )
    sent = json.loads(responses.calls[-1].request.body)
    assert "data" not in sent


@responses.activate
def test_pay_includes_data_when_present(options, token_body):
    client = _client(options, token_body)
    responses.add(responses.POST, f"{BASE_URL}/payments/v1", json={"transaction_id": 1}, status=200)
    client.pay(
        PayRequest(
            third_party_id_debit="b",
            service_id="s",
            sender_id="snd",
            recipient_id="r",
            amount_credit=Decimal("1"),
            currency_credit="USD",
            data={"passport": "AA1234567"},
        )
    )
    sent = json.loads(responses.calls[-1].request.body)
    assert sent["data"] == {"passport": "AA1234567"}


@responses.activate
def test_postcheck_maps_status_enum(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/postcheck",
        json={"transaction_id": 7, "status": 3, "error": "boom"},
        status=200,
    )
    result = client.postcheck(7)
    assert result.status is TransactionStatus.FAILED
    assert result.status.is_terminal()
    assert result.error == "boom"


@responses.activate
def test_cancel_maps_status_enum(options, token_body):
    client = _client(options, token_body)
    responses.add(responses.POST, f"{BASE_URL}/payments/v1/cancel", json={"status": 4}, status=200)
    result = client.cancel(99)
    assert result.status is TransactionStatus.CANCEL_PENDING
    assert not result.status.is_terminal()


@responses.activate
def test_error_mapping(options, token_body):
    client = _client(options, token_body)
    cases = [
        (400, MilkywayValidationError),
        (401, MilkywayAuthError),
        (402, MilkywayExposureBlockedError),
        (404, MilkywayNotFoundError),
        (503, MilkywayServiceUnavailableError),
    ]
    for status, exc in cases:
        responses.reset()
        responses.add(responses.POST, TOKEN_URL, json={"access_token": "t", "expires_in": 300}, status=200)
        responses.add(
            responses.GET,
            f"{BASE_URL}/payments/v1/postcheck",
            json={"error": f"err-{status}"},
            status=status,
        )
        try:
            client.postcheck(1)
            assert False, f"expected {exc} for {status}"
        except exc as ex:  # type: ignore[misc]
            assert ex.status_code == status
            assert ex.message == f"err-{status}"


@responses.activate
def test_401_triggers_refresh_and_replay(options):
    # token endpoint: first "stale", then "fresh"
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "stale", "expires_in": 300}, status=200)
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "fresh", "expires_in": 300}, status=200)
    # API: first 401, then 200
    responses.add(responses.GET, f"{BASE_URL}/payments/v1/postcheck", json={"error": "nope"}, status=401)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/postcheck",
        json={"transaction_id": 5, "status": 1},
        status=200,
    )

    client = MilkywayPaymentsClient(options)
    result = client.postcheck(5)
    assert result.status is TransactionStatus.DONE

    pc_calls = [c for c in responses.calls if "postcheck" in c.request.url]
    assert len(pc_calls) == 2
    assert pc_calls[0].request.headers["Authorization"] == "Bearer stale"
    assert pc_calls[1].request.headers["Authorization"] == "Bearer fresh"


@responses.activate
def test_401_persisting_raises_auth_error(options):
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "a", "expires_in": 300}, status=200)
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "b", "expires_in": 300}, status=200)
    responses.add(responses.GET, f"{BASE_URL}/payments/v1/postcheck", json={"error": "x"}, status=401)
    responses.add(responses.GET, f"{BASE_URL}/payments/v1/postcheck", json={"error": "x"}, status=401)

    client = MilkywayPaymentsClient(options)
    try:
        client.postcheck(1)
        assert False
    except MilkywayAuthError:
        pass


@responses.activate
def test_plain_text_500_body_used_as_message(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/healthcheck",
        body="recipient down",
        status=500,
        content_type="text/plain",
    )
    try:
        client.healthcheck("b", "s")
        assert False
    except MilkywayServiceUnavailableError as ex:
        assert ex.message == "recipient down"
        assert ex.status_code == 500
