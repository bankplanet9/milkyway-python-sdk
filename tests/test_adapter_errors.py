"""Typed errors for recipient-bank outcomes: 422 rejected, 502 connector failure,
503 naming the failed service, and the postcheck reason codes."""

from __future__ import annotations

from decimal import Decimal

import pytest
import responses

import milkyway_payments
from milkyway_payments import (
    MilkywayApiError,
    MilkywayPaymentRejectedError,
    MilkywayPaymentsClient,
    MilkywayRecipientBankError,
    MilkywayServiceUnavailableError,
    MilkywayValidationError,
    PayRequest,
    PrecheckRequest,
    StatusReason,
    TransactionStatus,
)

from conftest import BASE_URL, TOKEN_URL


def _client(options, token_body) -> MilkywayPaymentsClient:
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    return MilkywayPaymentsClient(options)


def _precheck_request() -> PrecheckRequest:
    return PrecheckRequest(
        third_party_id_debit="bank-b",
        service_id="wallet",
        recipient_id="992900000000",
        amount_credit=Decimal("10.00"),
        currency_credit="USD",
    )


def _pay_request() -> PayRequest:
    return PayRequest(
        third_party_id_debit="bank-b",
        service_id="wallet",
        sender_id="snd-1",
        recipient_id="992900000000",
        amount_credit=Decimal("10.00"),
        currency_credit="USD",
    )


@responses.activate
def test_precheck_422_raises_payment_rejected(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/precheck",
        json={"error": "ErrPaymentRejected"},
        status=422,
    )
    with pytest.raises(MilkywayPaymentRejectedError) as info:
        client.precheck(_precheck_request())
    err = info.value
    assert isinstance(err, MilkywayApiError)
    assert not isinstance(err, MilkywayServiceUnavailableError)
    assert err.status_code == 422
    assert err.error_code == "ErrPaymentRejected"
    assert err.error_code == StatusReason.PAYMENT_REJECTED


@responses.activate
def test_pay_with_key_422_raises_payment_rejected(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1",
        json={"error": "ErrPaymentRejected"},
        status=422,
    )
    with pytest.raises(MilkywayPaymentRejectedError):
        client.pay(_pay_request(), idempotency_key="idem-422")


@pytest.mark.parametrize(
    "method, path, call",
    [
        ("POST", "/payments/v1/precheck", lambda c: c.precheck(_precheck_request())),
        ("POST", "/payments/v1", lambda c: c.pay(_pay_request())),
        ("POST", "/payments/v1/cancel", lambda c: c.cancel(42)),
    ],
)
@responses.activate
def test_502_raises_recipient_bank_error(options, token_body, method, path, call):
    client = _client(options, token_body)
    responses.add(method, f"{BASE_URL}{path}", json={"error": "ErrRecipientBankError"}, status=502)
    with pytest.raises(MilkywayRecipientBankError) as info:
        call(client)
    err = info.value
    assert isinstance(err, MilkywayServiceUnavailableError)
    assert err.status_code == 502
    assert err.error_code == "ErrRecipientBankError"


@responses.activate
def test_502_is_caught_by_service_unavailable_handler(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/cancel",
        json={"error": "ErrRecipientBankError"},
        status=502,
    )
    try:
        client.cancel(42)
        assert False, "expected an error"
    except MilkywayServiceUnavailableError as ex:
        assert type(ex) is MilkywayRecipientBankError


@responses.activate
def test_cancel_503_exposes_failed_service(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/cancel",
        json={
            "error": "ErrServiceUnavailable",
            "service_id": "wallet",
            "third_party_id": "recipient-bank",
        },
        status=503,
    )
    with pytest.raises(MilkywayServiceUnavailableError) as info:
        client.cancel(42)
    err = info.value
    assert type(err) is MilkywayServiceUnavailableError
    assert err.status_code == 503
    assert err.error_code == "ErrServiceUnavailable"
    assert err.service_id == "wallet"
    assert err.third_party_id == "recipient-bank"


@responses.activate
def test_plain_text_5xx_has_no_error_code(options, token_body):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/healthcheck",
        body="recipient down",
        status=500,
        content_type="text/plain",
    )
    with pytest.raises(MilkywayServiceUnavailableError) as info:
        client.healthcheck("bank-b", "wallet")
    assert info.value.error_code is None
    assert info.value.service_id is None
    assert info.value.third_party_id is None


@pytest.mark.parametrize("field", ["recipient_id", "currency_credit"])
@responses.activate
def test_400_exposes_field(options, token_body, field):
    client = _client(options, token_body)
    responses.add(
        responses.POST,
        f"{BASE_URL}/payments/v1/precheck",
        json={"error": "ErrRecipientInvalid", "field": field},
        status=400,
    )
    with pytest.raises(MilkywayValidationError) as info:
        client.precheck(_precheck_request())
    assert info.value.field == field
    assert info.value.error_code == "ErrRecipientInvalid"


def test_status_reason_codes():
    assert StatusReason.PAYMENT_REJECTED == "ErrPaymentRejected"
    assert StatusReason.RECIPIENT_NOT_FOUND == "ErrRecipientNotFound"
    assert StatusReason.RECIPIENT_INVALID == "ErrRecipientInvalid"
    assert StatusReason.SERVICE_UNAVAILABLE == "ErrServiceUnavailable"
    assert StatusReason.PAYMENT_CANNOT_BE_CANCELED == "ErrPaymentCannotBeCanceled"
    assert "StatusReason" in milkyway_payments.__all__
    assert "MilkywayPaymentRejectedError" in milkyway_payments.__all__
    assert "MilkywayRecipientBankError" in milkyway_payments.__all__


@pytest.mark.parametrize("code", ["ErrRecipientNotFound", "ErrSomethingAddedLater"])
@responses.activate
def test_postcheck_error_is_a_plain_string_code(options, token_body, code):
    client = _client(options, token_body)
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/postcheck",
        json={"transaction_id": 7, "status": 3, "error": code},
        status=200,
    )
    result = client.postcheck(7)
    assert result.status is TransactionStatus.FAILED
    assert type(result.error) is str
    assert result.error == code
    assert (result.error == StatusReason.RECIPIENT_NOT_FOUND) == (code == "ErrRecipientNotFound")
