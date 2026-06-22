# MilkyWay Payments SDK for Python

[![PyPI](https://img.shields.io/pypi/v/milkyway-payments.svg?logo=pypi)](https://pypi.org/project/milkyway-payments/)
[![Downloads](https://img.shields.io/pypi/dm/milkyway-payments.svg)](https://pypi.org/project/milkyway-payments/)
[![CI](https://github.com/bankplanet9/milkyway-python-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/bankplanet9/milkyway-python-sdk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Official Python client for the **MilkyWay Payments API** (`/payments/v1`) — the
partner-facing API that banks use to initiate, quote, track, and cancel
cross-bank payments.

Batteries included:

- **Keycloak client-credentials auth** with in-memory token caching, automatic
  refresh ~30s before expiry, single-flight acquisition, and a one-shot
  refresh-and-replay on `401`.
- **Retries** (exponential backoff + jitter via `urllib3`) on transient failures
  (5xx, 408, network), with deterministic errors (400/401/402/404) never retried.
- **Typed models & exceptions** — money is `decimal.Decimal` (parsed losslessly
  from JSON numbers), status is an `IntEnum`, and each HTTP error maps to a
  specific exception type.
- **Idempotency-key passthrough** on `pay` (a `pay` without a key is sent exactly
  once — never auto-retried).
- A **`wait_for_completion`** polling helper with exponential backoff and a
  timeout budget.
- Full type hints and a `py.typed` marker.

## Install

```bash
pip install milkyway-payments
```

The distribution is `milkyway-payments`; the import package is `milkyway_payments`.
Requires Python 3.8+. Bring your Keycloak `client_id` / `client_secret` and you're
ready.

## Quick start

```python
from decimal import Decimal
from milkyway_payments import (
    MilkywayPaymentsClient, MilkywayOptions, PrecheckRequest, PayRequest,
)

client = MilkywayPaymentsClient(MilkywayOptions(
    base_url="https://milkyway.stage.planet9.ae",
    token_url="https://keycloak.ac8o.planet9.ae/realms/planet9-stage/protocol/openid-connect/token",
    client_id="your-client-id",       # issued to your institution
    client_secret="your-client-secret",
))

# 1. Is the recipient bank's service online?
client.healthcheck("bank-beta", "card-payout")

# 2. Quote the payment (FX markup + commission applied here).
quote = client.precheck(PrecheckRequest(
    third_party_id_debit="bank-beta",
    service_id="card-payout",
    recipient_id="recipient-9999",
    amount_credit=Decimal("100.00"),
    currency_credit="USD",
))
print(f"Rate {quote.rate}, debit {quote.amount_debit} {quote.currency_debit}, commission {quote.commission}")

# 3. Initiate the payment. Pass an idempotency_key so retries are safe.
import uuid
transaction_id = client.pay(PayRequest(
    third_party_id_debit="bank-beta",
    service_id="card-payout",
    sender_id="sender-0001",
    recipient_id="recipient-9999",
    amount_credit=Decimal("100.00"),
    currency_credit="USD",
    data={"passport": "AA1234567"},
), idempotency_key=str(uuid.uuid4()))

# 4. Poll until the payment reaches a terminal status.
result = client.wait_for_completion(transaction_id)
print(f"Final status: {result.status.name}")
```

`MilkywayPaymentsClient` is also a context manager (`with MilkywayPaymentsClient(...) as client:`)
and exposes `.close()` to release its HTTP sessions.

## The `data` field

Each service requires extra per-partner fields (sender name, document number,
birthday, …) in the `data` dictionary. **Which keys are required depends on your
`service_id` and the recipient bank** — look them up in the Услуги registry. The
server validates `data` against the service's JSON Schema during precheck, so a
missing field is rejected before any money moves. Omit `data` (leave it `None`)
and it is not sent on the wire.

## Errors

All API errors raise a subclass of `MilkywayApiError` (carrying `status_code`,
`message`, and the raw `response_body`):

| HTTP | Exception | Meaning |
| --- | --- | --- |
| 400 | `MilkywayValidationError` | Bad request (invalid amount, missing field, unresolvable FX rate). |
| 401 | `MilkywayAuthError` | Token missing/invalid (also raised if token acquisition fails). |
| 402 | `MilkywayExposureBlockedError` | Payment would breach a block-action exposure limit. |
| 404 | `MilkywayNotFoundError` | Transaction not found or not owned by your institution. |
| 5xx | `MilkywayServiceUnavailableError` | API or downstream recipient unavailable (retried automatically first). |

## Retries & idempotency

Transient failures are retried automatically with exponential backoff + jitter
(tunable via `MilkywayOptions.max_retries` / `retry_base_delay`). **`pay` is only
auto-retried when you supply an `idempotency_key`** — without one, a retry could
create a duplicate payment, so the SDK sends it exactly once.

## Configuration

| Option | Default | Purpose |
| --- | --- | --- |
| `base_url` | — (required) | Payments API base URL. |
| `token_url` | — (required) | Keycloak token endpoint. |
| `client_id` / `client_secret` | — (required) | Your institution's credentials. |
| `scope` | `None` | Optional OAuth scope. |
| `token_refresh_skew` | `30.0` (s) | Refresh this long before token expiry. |
| `request_timeout` | `30.0` (s) | Per-attempt request timeout. |
| `max_retries` | `3` | Max transient-failure retries. |
| `retry_base_delay` | `0.5` (s) | Base delay for exponential backoff. |

## Developing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Releasing

Releases are **fully automated** by [semantic-release](https://semantic-release.gitbook.io/)
on every push to `main`:

1. Conventional commits are analysed (`feat:` → minor, `fix:`/`perf:` → patch,
   `!` / `BREAKING CHANGE` → major). No releasable commits → no release.
2. The computed version is written into `pyproject.toml` and `__init__.py`, the
   distribution is built with `python -m build`, and a GitHub release + `vX.Y.Z`
   tag are created.
3. A separate workflow, triggered on the published GitHub release, uploads the
   built artifacts to **PyPI via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)**
   (OIDC — no long-lived API token stored anywhere).

### One-time PyPI Trusted Publisher setup (maintainers)

Before the first publish can succeed, register the trusted publisher on PyPI:

1. Sign in to <https://pypi.org> and go to **Your projects → milkyway-payments →
   Settings → Publishing** (or, before the project exists, **Account settings →
   Publishing → Add a pending publisher**).
2. Add a **GitHub Actions** trusted publisher with:
   - **Owner**: `bankplanet9`
   - **Repository**: `milkyway-python-sdk`
   - **Workflow name**: `publish.yml`
   - **Environment**: `pypi`
3. In the GitHub repo, create an **Environment** named `pypi` and set the
   repository **variable** `PUBLISH_ENABLED` to `true`. The publish job is gated
   on `vars.PUBLISH_ENABLED == 'true'`, so until the trusted-publisher policy and
   this variable exist, releases tag and build but skip the PyPI upload (they
   never fail).

No API tokens or passwords are stored anywhere — PyPI mints a short-lived OIDC
credential at publish time.

## License

MIT — see [LICENSE](LICENSE).
