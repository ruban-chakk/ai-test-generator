import asyncio
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.services.oidc import OIDCClient, OIDCConfigurationError, OIDCProviderError, allowed_email_domain


def oidc_settings() -> Settings:
    return Settings(
        _env_file=None,
        oidc_enabled=True,
        oidc_issuer="https://identity.example",
        oidc_client_id="test-generator",
        oidc_client_secret="client-secret",
        oidc_authorization_endpoint="https://identity.example/authorize",
        oidc_token_endpoint="https://identity.example/token",
        oidc_jwks_uri="https://identity.example/jwks",
        oidc_redirect_uri="https://app.example/api/v1/auth/oidc/callback",
        oidc_allowed_email_domains="example.com, subsidiary.example",
    )


def test_authorization_url_binds_state_nonce_and_redirect() -> None:
    url = OIDCClient(oidc_settings()).authorization_url(state="signed-state", nonce="random-nonce")
    query = parse_qs(urlparse(url).query)
    assert query == {
        "response_type": ["code"],
        "client_id": ["test-generator"],
        "redirect_uri": ["https://app.example/api/v1/auth/oidc/callback"],
        "scope": ["openid profile email"],
        "state": ["signed-state"],
        "nonce": ["random-nonce"],
    }


def test_code_exchange_validates_signed_identity_and_nonce() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    now = datetime.now(timezone.utc)
    id_token = jwt.encode(
        {
            "sub": "enterprise-user-1",
            "iss": "https://identity.example",
            "aud": "test-generator",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": "expected-nonce",
            "email": "QA.User@example.com",
            "email_verified": True,
            "preferred_username": "qa.user",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            assert b"client_secret=client-secret" in request.content
            return httpx.Response(200, json={"id_token": id_token})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            identity = await OIDCClient(oidc_settings(), client).exchange(
                code="authorization-code",
                nonce="expected-nonce",
            )
        assert identity.subject == "enterprise-user-1"
        assert identity.email == "qa.user@example.com"
        assert identity.username == "qa.user"

    asyncio.run(scenario())


def test_nonce_mismatch_and_unconfigured_oidc_fail_closed() -> None:
    with pytest.raises(OIDCConfigurationError):
        OIDCClient(Settings(_env_file=None))
    config = oidc_settings()
    client = OIDCClient(config)
    with pytest.raises(OIDCProviderError, match="unsupported signing algorithm"):
        client._validate_id_token(
            jwt.encode({"nonce": "wrong"}, "test-secret-at-least-thirty-two-bytes", algorithm="HS256"),
            {"keys": []},
            "expected",
        )


def test_email_domain_allowlist_is_exact() -> None:
    config = oidc_settings()
    assert allowed_email_domain("person@example.com", config)
    assert not allowed_email_domain("person@attacker-example.com", config)
