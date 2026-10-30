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
  (5xx, 408, network), with deterministic errors (400/401/402/404/422) never retried.
- **Typed models & exceptions** — money is `decimal.Decimal` (parsed losslessly
  from JSON numbers), status is an `IntEnum`, the payer and beneficiary are typed
  `PartyInfo` dataclasses, and each HTTP error maps to a specific exception type.
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
from datetime import date
from decimal import Decimal
from milkyway_payments import (
    MilkywayPaymentsClient, MilkywayOptions, PrecheckRequest, PayRequest,
    PartyInfo, PartyName, PartyType, IdentityDocumentType,
)

client = MilkywayPaymentsClient(MilkywayOptions(
    base_url="https://milkyway.stage.planet9.ae",
    token_url="https://keycloak.ac8o.planet9.ae/realms/planet9-stage/protocol/openid-connect/token",
    client_id="your-client-id",       # issued to your institution
    client_secret="your-client-secret",
))

# 1. Is the recipient bank's service online?
client.healthcheck("bank-beta", "card-payout")

# The payer and the beneficiary, in the canonical model. The service's
# `party_profile` from discovery says which fields its recipient bank requires.
sender = PartyInfo(
    party_type=PartyType.NATURAL,
    name=PartyName(first="Ivan", last="Petrov", full="Petrov Ivan Sergeevich"),
    date_of_birth=date(1990, 4, 18),
    identity_document_type=IdentityDocumentType.PASSPORT,
    identity_document_number="AB1234567",
)
recipient = PartyInfo(party_type=PartyType.NATURAL, name=PartyName(full="Karimov Ali"))

# 2. Quote the payment (FX markup + commission applied here).
quote = client.precheck(PrecheckRequest(
    third_party_id_debit="bank-beta",
    service_id="card-payout",
    recipient_id="recipient-9999",
    amount_credit=Decimal("100.00"),
    currency_credit="USD",
    sender_info=sender,
    recipient_info=recipient,
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
    sender_info=sender,
    recipient_info=recipient,
), idempotency_key=str(uuid.uuid4()))

# 4. Poll until the payment reaches a terminal status.
result = client.wait_for_completion(transaction_id)
print(f"Final status: {result.status.name}")
```

`MilkywayPaymentsClient` is also a context manager (`with MilkywayPaymentsClient(...) as client:`)
and exposes `.close()` to release its HTTP sessions.

## Discovery

Before quoting a payment you can discover which destinations are reachable and
which services each one exposes. `discovery()` returns a list of `Destination`
objects (optionally filtered by ISO 3166-1 alpha-2 `country`, case-insensitive);
`service_schema()` returns the Draft-2020 JSON Schema of a service's non-identity
`data` extras.

```python
# List every reachable destination, or filter by country.
for dest in client.discovery(country="TJ"):
    print(dest.third_party_id, dest.partner_name, dest.country)
    for svc in dest.services:
        print("  ", svc.service_id, svc.payout_method, svc.payout_currencies)
        profile = svc.party_profile
        if profile and profile.sender_info:
            print("   sender needs", profile.sender_info.required)

# Fetch the JSON Schema of one service's non-identity `data` extras.
schema = client.service_schema("bank-beta", "card-payout")
print(schema.get("properties"))
```

Each `Destination` carries `third_party_id`, optional `partner_name` / `country`,
and a list of `ServiceCapability` (`service_id`, `payout_method`, optional
`recipient`, `payout_currencies` and `party_profile`). `party_profile` says which
`sender_info` / `recipient_info` fields the recipient bank requires and accepts
(see [Payer and beneficiary](#payer-and-beneficiary)). The per-service `data`
schema is **not** included in the listing — fetch it with `service_schema` when
you need it.

## Payer and beneficiary

The identity of your customer (the payer) and of the beneficiary travels in
`sender_info` and `recipient_info` on `PrecheckRequest` and `PayRequest` — two
`PartyInfo` objects in one canonical model (FATF Travel Rule / ISO 20022 /
IVMS101), the same for every recipient bank and service. You map your customer
data to it once; each bank's connector converts it to that bank's own format.
The account, card or phone stays in `sender_id` / `recipient_id`.

| Field | Format |
| --- | --- |
| `party_type` | `PartyType.NATURAL` (required). `PartyType.LEGAL` exists in the model but the API refuses it for now. |
| `name` | `PartyName(first, last, full)`, text. `full` is the name as in the document, family name first, with a patronymic if any. |
| `date_of_birth` | A `datetime.date`, or an ISO 8601 `YYYY-MM-DD` string. |
| `identity_document_type` | `IdentityDocumentType.PASSPORT`, `NATIONAL_ID`, `DRIVER_LICENSE`, `RESIDENCE_PERMIT`, `TAX_ID`, `SOCIAL_SECURITY` or `OTHER`. Required with `identity_document_number`. |
| `identity_document_number` | Series and number together, as in the document. |
| `identity_document_country`, `country_of_residence` | ISO 3166-1 alpha-2, upper case (`"TJ"`). |
| `address` | `PartyAddress(country, city, street, building, postal_code, line)` — `country` (alpha-2) is required when an address is sent; `line` holds up to 7 free-text lines. |

Every field except `party_type` is optional; empty fields (and an empty `name`
or `address`) are left out of the request. Text values are at most 256
characters.

Which fields a service needs is set by its recipient bank and published as the
service's `party_profile` in `discovery()`: `required` and `accepted` field paths
(`"name.first"`, `"date_of_birth"`, … — see `PartyFieldPath`) for each side, and,
when the bank takes only some document kinds, `identity_document_types`. Send the
fields you have; fields the bank does not use are ignored. A missing required
field or an invalid value raises `MilkywayValidationError` whose `field` names it
by its path (e.g. `sender_info.date_of_birth`).

## Service-specific extras (the `data` field)

**Never put identity in `data`** (no sender name, birthday, passport or document
number there) — the API does not read it from `data`. `data` carries only what a
service needs beyond the parties; most services take no `data` fields. When one
does, `service_schema()` returns its JSON Schema. The browsable registry of
banks, services, party profiles and `data` fields is the
[MilkyWay Handbook](https://docs.planet9.ae/site/milkyway-handbook/en/) (section
**Services**). Omit `data` (leave it `None`) and it is not sent on the wire.

## Errors

All API errors raise a subclass of `MilkywayApiError` (carrying `status_code`,
`message`, the raw `response_body`, and `error_code` — the body's `error` code
verbatim, e.g. `ErrPaymentRejected`). On a field-level 400, `field` names the
request field at fault — e.g. `amount_credit`, `currency_credit`, `recipient_id`
(the recipient bank reports the recipient invalid), or a party field by its path
such as `sender_info.date_of_birth`:

| HTTP | Exception | Meaning |
| --- | --- | --- |
| 400 | `MilkywayValidationError` | Bad request (invalid amount, missing field, recipient invalid). |
| 401 | `MilkywayAuthError` | Token missing/invalid (also raised if token acquisition fails). |
| 402 | `MilkywayExposureBlockedError` | Payment would breach a block-action exposure limit. |
| 404 | `MilkywayNotFoundError` | Transaction not found or not owned by your institution. |
| 422 | `MilkywayPaymentRejectedError` | The recipient bank refused the payment on its merits (`precheck`, `pay`). Not retryable; nothing was created. |
| 502 | `MilkywayRecipientBankError` | The recipient bank's connector failed unclassifiably (`precheck`, `pay`, `cancel`). Nothing was created; retry later or use another service. Subclass of `MilkywayServiceUnavailableError`. |
| 5xx | `MilkywayServiceUnavailableError` | API or downstream recipient unavailable, or the recipient bank quoted no usable FX rate for a cross-currency payment. On a 503, `service_id` and `third_party_id` name the service that failed. |

5xx errors (including 502) are retried automatically first; 4xx errors (including
422) never are.

```python
from milkyway_payments import (
    MilkywayPaymentRejectedError,
    MilkywayServiceUnavailableError,
)

try:
    tx_id = client.pay(pay_request, idempotency_key=key)
except MilkywayPaymentRejectedError:
    ...  # the recipient bank said no: do not resend
except MilkywayServiceUnavailableError as ex:  # also catches MilkywayRecipientBankError
    ...  # transient: retry later with the same idempotency_key
```

A failed payment's `PostcheckResult.error` is a reason **code**, never the bank's
own text. It stays a plain `str`; compare it against the `StatusReason` constants:

| `StatusReason` | Code |
| --- | --- |
| `PAYMENT_REJECTED` | `ErrPaymentRejected` — the bank declined (also any reason given without a code) |
| `RECIPIENT_NOT_FOUND` | `ErrRecipientNotFound` |
| `RECIPIENT_INVALID` | `ErrRecipientInvalid` |
| `SERVICE_UNAVAILABLE` | `ErrServiceUnavailable` |
| `PAYMENT_CANNOT_BE_CANCELED` | `ErrPaymentCannotBeCanceled` |

```python
from milkyway_payments import StatusReason, TransactionStatus

result = client.wait_for_completion(tx_id)
if result.status is TransactionStatus.FAILED and result.error == StatusReason.RECIPIENT_NOT_FOUND:
    ...
```

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
