from __future__ import annotations

import pytest

from milkyway_payments import MilkywayOptions

BASE_URL = "https://milkyway.test.local"
TOKEN_URL = "https://keycloak.test.local/realms/test/protocol/openid-connect/token"


@pytest.fixture
def options() -> MilkywayOptions:
    return MilkywayOptions(
        base_url=BASE_URL,
        token_url=TOKEN_URL,
        client_id="client-abc",
        client_secret="secret-xyz",
        max_retries=3,
        retry_base_delay=0.0,  # keep tests fast
        request_timeout=5.0,
    )


@pytest.fixture
def token_body() -> dict:
    return {"access_token": "tok-1", "expires_in": 300, "token_type": "Bearer"}
