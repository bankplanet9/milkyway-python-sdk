"""Transport-level resilience tests against a real local HTTP server.

These exercise the actual urllib3 Retry stack (which ``responses`` bypasses):
retry-on-5xx, no-retry-on-402, and pay-without-key sent exactly once.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from milkyway_payments import (
    MilkywayExposureBlockedError,
    MilkywayOptions,
    MilkywayPaymentRejectedError,
    MilkywayPaymentsClient,
    MilkywayRecipientBankError,
    MilkywayServiceUnavailableError,
    PayRequest,
    PrecheckRequest,
)


class _Recorder:
    def __init__(self) -> None:
        self.script: dict[str, list[tuple[int, str]]] = {}
        self.hits: dict[str, int] = {}
        self.lock = threading.Lock()

    def program(self, path: str, responses: list[tuple[int, str]]) -> None:
        self.script[path] = responses
        self.hits[path] = 0

    def next_response(self, path: str) -> tuple[int, str]:
        with self.lock:
            n = self.hits.get(path, 0)
            self.hits[path] = n + 1
            script = self.script.get(path, [(200, "{}")])
            return script[min(n, len(script) - 1)]


@pytest.fixture
def server():
    recorder = _Recorder()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _respond(self):
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            status, body = recorder.next_response(path)
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _respond
        do_POST = _respond

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    base = f"http://{host}:{port}"
    recorder.base_url = base  # type: ignore[attr-defined]
    yield recorder, base
    httpd.shutdown()


def _options(base: str, token_path: str = "/token") -> MilkywayOptions:
    return MilkywayOptions(
        base_url=base,
        token_url=base + token_path,
        client_id="c",
        client_secret="s",
        max_retries=3,
        retry_base_delay=0.0,
        request_timeout=5.0,
    )


def test_retry_on_5xx_then_success(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program(
        "/payments/v1/postcheck",
        [(503, '{"error":"down"}'), (503, '{"error":"down"}'), (200, '{"transaction_id":1,"status":1}')],
    )
    client = MilkywayPaymentsClient(_options(base))
    result = client.postcheck(1)
    assert result.transaction_id == 1
    assert recorder.hits["/payments/v1/postcheck"] == 3  # 2 failures + success


def test_no_retry_on_402(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program("/payments/v1/precheck", [(402, '{"error":"blocked"}')])
    client = MilkywayPaymentsClient(_options(base))
    from milkyway_payments import PrecheckRequest

    with pytest.raises(MilkywayExposureBlockedError):
        client.precheck(
            PrecheckRequest(
                third_party_id_debit="b",
                service_id="s",
                recipient_id="r",
                amount_credit=Decimal("1"),
                currency_credit="USD",
            )
        )
    assert recorder.hits["/payments/v1/precheck"] == 1  # deterministic, not retried


def test_pay_without_key_is_not_retried(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program("/payments/v1", [(503, '{"error":"down"}')])
    client = MilkywayPaymentsClient(_options(base))

    with pytest.raises(MilkywayServiceUnavailableError):
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
    assert recorder.hits["/payments/v1"] == 1  # sent exactly once (duplicate-safety)


def test_pay_with_key_is_retried(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program(
        "/payments/v1",
        [(503, '{"error":"down"}'), (200, '{"transaction_id":77}')],
    )
    client = MilkywayPaymentsClient(_options(base))
    tx = client.pay(
        PayRequest(
            third_party_id_debit="b",
            service_id="s",
            sender_id="snd",
            recipient_id="r",
            amount_credit=Decimal("1"),
            currency_credit="USD",
        ),
        idempotency_key="idem-1",
    )
    assert tx == 77
    assert recorder.hits["/payments/v1"] == 2  # retried with the key


def _pay_request() -> PayRequest:
    return PayRequest(
        third_party_id_debit="b",
        service_id="s",
        sender_id="snd",
        recipient_id="r",
        amount_credit=Decimal("1"),
        currency_credit="USD",
    )


def test_no_retry_on_422(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program("/payments/v1", [(422, '{"error":"ErrPaymentRejected"}')])
    client = MilkywayPaymentsClient(_options(base))

    with pytest.raises(MilkywayPaymentRejectedError):
        client.pay(_pay_request(), idempotency_key="idem-422")
    assert recorder.hits["/payments/v1"] == 1  # deterministic, not retried even with a key


def test_502_is_retried_then_raises_recipient_bank_error(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program("/payments/v1/precheck", [(502, '{"error":"ErrRecipientBankError"}')])
    client = MilkywayPaymentsClient(_options(base))

    with pytest.raises(MilkywayRecipientBankError):
        client.precheck(
            PrecheckRequest(
                third_party_id_debit="b",
                service_id="s",
                recipient_id="r",
                amount_credit=Decimal("1"),
                currency_credit="USD",
            )
        )
    assert recorder.hits["/payments/v1/precheck"] == 4  # first attempt + max_retries


def test_502_then_success_is_retried(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program(
        "/payments/v1/cancel",
        [(502, '{"error":"ErrRecipientBankError"}'), (200, '{"status":2}')],
    )
    client = MilkywayPaymentsClient(_options(base))
    assert client.cancel(9).status == 2
    assert recorder.hits["/payments/v1/cancel"] == 2


def test_pay_without_key_502_is_not_retried(server):
    recorder, base = server
    recorder.program("/token", [(200, '{"access_token":"t","expires_in":300}')])
    recorder.program("/payments/v1", [(502, '{"error":"ErrRecipientBankError"}')])
    client = MilkywayPaymentsClient(_options(base))

    with pytest.raises(MilkywayServiceUnavailableError) as info:
        client.pay(_pay_request())
    assert isinstance(info.value, MilkywayRecipientBankError)
    assert recorder.hits["/payments/v1"] == 1  # sent exactly once (duplicate-safety)


def test_validate_rejects_missing_fields(server):
    recorder, base = server
    with pytest.raises(ValueError):
        MilkywayPaymentsClient(
            MilkywayOptions(base_url="", token_url=base, client_id="c", client_secret="s")
        )
