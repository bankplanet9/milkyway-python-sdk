from __future__ import annotations

import threading

import responses

from milkyway_payments import MilkywayAuthError
from milkyway_payments.auth import KeycloakTokenProvider

from conftest import TOKEN_URL


@responses.activate
def test_token_is_cached_across_calls(options, token_body):
    responses.add(responses.POST, TOKEN_URL, json=token_body, status=200)
    provider = KeycloakTokenProvider(options)

    assert provider.get_access_token() == "tok-1"
    assert provider.get_access_token() == "tok-1"

    assert len(responses.calls) == 1  # only one acquisition


@responses.activate
def test_token_refreshes_before_expiry(options):
    clock = {"t": 0.0}
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "a", "expires_in": 100}, status=200)
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "b", "expires_in": 100}, status=200)

    provider = KeycloakTokenProvider(options, time_fn=lambda: clock["t"])
    assert provider.get_access_token() == "a"

    # skew is 30s; expires at 100, so still cached at 69, refreshed at 71.
    clock["t"] = 69.0
    assert provider.get_access_token() == "a"
    clock["t"] = 71.0
    assert provider.get_access_token() == "b"


@responses.activate
def test_force_refresh_bypasses_cache(options, token_body):
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "a", "expires_in": 300}, status=200)
    responses.add(responses.POST, TOKEN_URL, json={"access_token": "b", "expires_in": 300}, status=200)

    provider = KeycloakTokenProvider(options)
    assert provider.get_access_token() == "a"
    assert provider.get_access_token(force_refresh=True) == "b"


@responses.activate
def test_single_flight_one_acquisition_under_concurrency(options):
    in_flight = threading.Event()
    proceed = threading.Event()
    call_count = {"n": 0}

    def cb(request):
        call_count["n"] += 1
        in_flight.set()  # signal: an acquisition is happening
        proceed.wait(timeout=5)  # hold it open while other callers pile up on the lock
        return (200, {}, '{"access_token": "tok", "expires_in": 300}')

    responses.add_callback(responses.POST, TOKEN_URL, callback=cb)
    provider = KeycloakTokenProvider(options)

    results: list[str] = []
    errors: list[Exception] = []

    def worker():
        try:
            results.append(provider.get_access_token())
        except Exception as ex:  # pragma: no cover
            errors.append(ex)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    threads[0].start()
    assert in_flight.wait(timeout=5)  # first caller is inside the acquisition
    for t in threads[1:]:
        t.start()  # these block on the single-flight lock
    proceed.set()  # let the in-flight acquisition complete
    for t in threads:
        t.join(timeout=5)

    assert not errors
    assert results == ["tok"] * 8
    assert call_count["n"] == 1  # single-flight collapsed to one fetch


@responses.activate
def test_token_acquisition_failure_raises_auth_error(options):
    responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_client"}, status=401)
    provider = KeycloakTokenProvider(options)

    try:
        provider.get_access_token()
        assert False, "expected MilkywayAuthError"
    except MilkywayAuthError as ex:
        assert ex.status_code == 401
