"""The public :class:`MilkywayPaymentsClient`.

Wraps the MilkyWay Payments API (``/payments/v1``) with Keycloak auth, transient
retries (exponential backoff + jitter on 5xx/408/network), typed models, typed
errors, idempotency-key passthrough, and a polling ``wait_for_completion``
helper.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional

import requests
from urllib3.util.retry import Retry

from .auth import KeycloakTokenProvider
from .exceptions import (
    MilkywayApiError,
    MilkywayAuthError,
    MilkywayExposureBlockedError,
    MilkywayNotFoundError,
    MilkywayServiceUnavailableError,
    MilkywayValidationError,
)
from .models import (
    CancelResult,
    Destination,
    MilkywayOptions,
    PayRequest,
    PollOptions,
    PostcheckResult,
    PrecheckRequest,
    PrecheckResult,
)

_PAYMENTS_PATH = "payments/v1"


def _dump_json(payload: Mapping[str, Any]) -> str:
    # Decimals must land on the wire as bare numbers. json with a custom encoder
    # would coerce to float; instead substitute placeholders and splice the exact
    # decimal text back in.
    placeholders: dict[str, str] = {}

    def _convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            token = f"@@DEC{len(placeholders)}@@"
            placeholders[token] = format(value, "f")
            return token
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_convert(v) for v in value]
        return value

    text = json.dumps(_convert(dict(payload)))
    for token, number in placeholders.items():
        text = text.replace(f'"{token}"', number)
    return text


class MilkywayPaymentsClient:
    """Client for the MilkyWay Payments API."""

    def __init__(
        self,
        options: MilkywayOptions,
        *,
        session: Optional[requests.Session] = None,
        token_session: Optional[requests.Session] = None,
        token_provider: Optional[KeycloakTokenProvider] = None,
    ) -> None:
        options.validate()
        self._options = options
        self._base_url = options.base_url.rstrip("/") + "/"

        self._session = session if session is not None else requests.Session()
        self._owns_session = session is None

        # A retry policy for transient failures only; deterministic 4xx never
        # retried. Applied per-request via a mounted adapter; pay-without-key
        # opts out by issuing a single-shot request.
        retry = Retry(
            total=options.max_retries,
            connect=options.max_retries,
            read=options.max_retries,
            status=options.max_retries,
            backoff_factor=options.retry_base_delay,
            backoff_jitter=options.retry_base_delay,
            status_forcelist=(408, 500, 502, 503, 504),
            allowed_methods=None,  # retry POST too; non-idempotent pay opts out
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        no_retry_adapter = requests.adapters.HTTPAdapter(max_retries=Retry(total=0))
        self._no_retry_session = requests.Session()
        self._no_retry_session.mount("http://", no_retry_adapter)
        self._no_retry_session.mount("https://", no_retry_adapter)

        self._token_provider = token_provider or KeycloakTokenProvider(
            options, session=token_session
        )

    # ------------------------------------------------------------------ API

    def healthcheck(self, third_party_id: str, service_id: str) -> str:
        """Return the recipient service's plain-text status string."""
        if not (third_party_id and third_party_id.strip()):
            raise ValueError("third_party_id is required.")
        if not (service_id and service_id.strip()):
            raise ValueError("service_id is required.")

        uri = (
            f"{_PAYMENTS_PATH}/healthcheck"
            f"?third_party_id={requests.utils.quote(third_party_id, safe='')}"
            f"&service_id={requests.utils.quote(service_id, safe='')}"
        )
        response = self._send("GET", uri)
        body = response.text
        if not response.ok:
            raise self._to_error(response.status_code, body)
        return body

    def discovery(self, country: Optional[str] = None) -> List[Destination]:
        """List reachable destinations and their payout services.

        Pass an ISO 3166-1 alpha-2 ``country`` (case-insensitive) to filter to a
        single country; omit it to list every destination. Each service's
        ``party_profile`` says which ``sender_info`` / ``recipient_info`` fields
        its recipient bank requires. The JSON Schema of a service's non-identity
        ``data`` extras is not included here — fetch it with
        :meth:`service_schema`.
        """
        uri = f"{_PAYMENTS_PATH}/discovery"
        if country:
            uri += f"?country={requests.utils.quote(country, safe='')}"
        response = self._send("GET", uri)
        return self._parse(
            response,
            lambda b: [Destination.from_dict(d) for d in b.get("destinations") or []],
        )

    def service_schema(self, third_party_id: str, service_id: str) -> Dict[str, Any]:
        """Return the Draft-2020 JSON Schema of a service's non-identity ``data`` extras."""
        if not (third_party_id and third_party_id.strip()):
            raise ValueError("third_party_id is required.")
        if not (service_id and service_id.strip()):
            raise ValueError("service_id is required.")

        uri = (
            f"{_PAYMENTS_PATH}/discovery"
            f"/{requests.utils.quote(third_party_id, safe='')}"
            f"/{requests.utils.quote(service_id, safe='')}"
            f"/schema"
        )
        response = self._send("GET", uri)
        return self._parse(response, lambda b: b)

    def precheck(self, request: PrecheckRequest) -> PrecheckResult:
        """Quote a payment (rate + commission) without creating it."""
        response = self._send(
            "POST",
            f"{_PAYMENTS_PATH}/precheck",
            body=_dump_json(request.to_payload()),
        )
        return self._parse(response, PrecheckResult.from_dict)

    def pay(
        self,
        request: PayRequest,
        idempotency_key: Optional[str] = None,
    ) -> int:
        """Initiate a payment; returns the created transaction id.

        Without an ``idempotency_key`` the request is sent exactly once (no
        auto-retry) so a retry cannot create a duplicate payment.
        """
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        response = self._send(
            "POST",
            _PAYMENTS_PATH,
            body=_dump_json(request.to_payload()),
            headers=headers,
            suppress_retry=not bool(idempotency_key),
        )
        parsed = self._parse(response, lambda b: b)
        return int(parsed["transaction_id"])

    def postcheck(self, transaction_id: int) -> PostcheckResult:
        """Fetch the current status of a transaction."""
        uri = f"{_PAYMENTS_PATH}/postcheck?transaction_id={transaction_id}"
        response = self._send("GET", uri)
        return self._parse(response, PostcheckResult.from_dict)

    def cancel(self, transaction_id: int) -> CancelResult:
        """Request cancellation of a transaction owned by your institution."""
        response = self._send(
            "POST",
            f"{_PAYMENTS_PATH}/cancel",
            body=_dump_json({"transaction_id": transaction_id}),
        )
        return self._parse(response, CancelResult.from_dict)

    def wait_for_completion(
        self,
        transaction_id: int,
        poll_options: Optional[PollOptions] = None,
    ) -> PostcheckResult:
        """Poll ``postcheck`` with exponential backoff until terminal or timeout.

        Returns the last observed status when the timeout budget is exhausted,
        even if non-terminal.
        """
        opts = poll_options or PollOptions()
        start = time.monotonic()
        delay = opts.initial_delay

        result = self.postcheck(transaction_id)
        while not result.status.is_terminal():
            if (time.monotonic() - start) + delay > opts.timeout:
                return result
            time.sleep(delay)
            delay = min(delay * opts.backoff_multiplier, opts.max_delay)
            result = self.postcheck(transaction_id)
        return result

    def close(self) -> None:
        """Release the underlying HTTP sessions owned by this client."""
        self._no_retry_session.close()
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> "MilkywayPaymentsClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -------------------------------------------------------------- internal

    def _send(
        self,
        method: str,
        path: str,
        *,
        body: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        suppress_retry: bool = False,
    ) -> requests.Response:
        url = self._base_url + path
        session = self._no_retry_session if suppress_retry else self._session

        def issue(force_refresh: bool) -> requests.Response:
            token = self._token_provider.get_access_token(force_refresh=force_refresh)
            req_headers = {"Authorization": f"Bearer {token}"}
            if body is not None:
                req_headers["Content-Type"] = "application/json"
            if headers:
                req_headers.update(headers)
            try:
                return session.request(
                    method,
                    url,
                    data=body.encode("utf-8") if body is not None else None,
                    headers=req_headers,
                    timeout=self._options.request_timeout,
                )
            except requests.RequestException as ex:
                raise MilkywayServiceUnavailableError(
                    0, f"Request to {path} failed: {ex}"
                ) from ex

        response = issue(force_refresh=False)
        if response.status_code == 401:
            # Token may be stale/revoked: refresh once and replay.
            response = issue(force_refresh=True)
        return response

    def _parse(self, response: requests.Response, factory: Callable[[Any], Any]) -> Any:
        body = response.text
        if not response.ok:
            raise self._to_error(response.status_code, body)
        try:
            parsed = json.loads(body, parse_float=Decimal)
        except ValueError as ex:
            raise MilkywayApiError(
                response.status_code, "Failed to parse the API response.", body
            ) from ex
        if parsed is None:
            raise MilkywayApiError(
                response.status_code, "The API returned an empty response.", body
            )
        return factory(parsed)

    def _to_error(self, status: int, body: str) -> MilkywayApiError:
        message = self._extract_error_message(body) or f"Request failed with status {status}."
        if status == 400:
            return MilkywayValidationError(message, body, self._extract_error_field(body))
        if status == 401:
            return MilkywayAuthError(message, body)
        if status == 402:
            return MilkywayExposureBlockedError(message, body)
        if status == 404:
            return MilkywayNotFoundError(message, body)
        if status >= 500:
            return MilkywayServiceUnavailableError(status, message, body)
        return MilkywayApiError(status, message, body)

    @staticmethod
    def _extract_error_message(body: str) -> Optional[str]:
        if not (body and body.strip()):
            return None
        try:
            doc = json.loads(body)
        except ValueError:
            # Non-JSON body (e.g. plain-text 500 from healthcheck) — use as-is.
            return body.strip()
        if isinstance(doc, dict):
            err = doc.get("error")
            if isinstance(err, str):
                return err
        return None

    @staticmethod
    def _extract_error_field(body: str) -> Optional[str]:
        try:
            doc = json.loads(body)
        except ValueError:
            return None
        if isinstance(doc, dict):
            field = doc.get("field")
            if isinstance(field, str):
                return field
        return None
