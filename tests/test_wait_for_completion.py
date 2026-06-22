from __future__ import annotations

import responses

from milkyway_payments import MilkywayPaymentsClient, PollOptions, TransactionStatus

from conftest import BASE_URL, TOKEN_URL


def _fast_poll() -> PollOptions:
    return PollOptions(initial_delay=0.0, max_delay=0.0, backoff_multiplier=1.0, timeout=5.0)


@responses.activate
def test_wait_polls_until_terminal(options, token_body):
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    for status in (0, 0, 1):
        responses.add(
            responses.GET,
            f"{BASE_URL}/payments/v1/postcheck",
            json={"transaction_id": 1, "status": status},
            status=200,
        )
    client = MilkywayPaymentsClient(options)
    result = client.wait_for_completion(1, _fast_poll())

    assert result.status is TransactionStatus.DONE
    pc = [c for c in responses.calls if "postcheck" in c.request.url]
    assert len(pc) == 3


@responses.activate
def test_wait_returns_last_status_on_timeout(options, token_body):
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    # always pending
    responses.add(
        responses.GET,
        f"{BASE_URL}/payments/v1/postcheck",
        json={"transaction_id": 1, "status": 0},
        status=200,
    )
    client = MilkywayPaymentsClient(options)
    opts = PollOptions(initial_delay=0.01, max_delay=0.01, backoff_multiplier=1.0, timeout=0.0)
    result = client.wait_for_completion(1, opts)
    # timeout budget 0 → returns first non-terminal observation immediately
    assert result.status is TransactionStatus.PENDING
