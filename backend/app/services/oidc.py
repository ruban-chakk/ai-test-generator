from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import Settings, settings


class OIDCConfigurationError(RuntimeError):
    """Raised when enterprise identity is not completely configured."""


class OIDCProviderError(RuntimeError):
    """Raised when an identity response cannot be securely validated."""


@dataclass(frozen=True)
class OIDCIdentity:
    subject: str
    email: str
    username: str


class OIDCClient:
    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        required = [
            config.oidc_issuer,
            config.oidc_client_id,
            config.oidc_client_secret,
            config.oidc_authorization_endpoint,
            config.oidc_token_endpoint,
            config.oidc_jwks_uri,
            config.oidc_redirect_uri,
        ]
        if not config.oidc_enabled or not all(required):
            raise OIDCConfigurationError("Enterprise OIDC is not configured")
        self._config = config
        self._client = client

    def authorization_url(self, *, state: str, nonce: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._config.oidc_client_id,
                "redirect_uri": self._config.oidc_redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
            }
        )
        return f"{self._config.oidc_authorization_endpoint}?{query}"

    async def exchange(self, *, code: str, nonce: str) -> OIDCIdentity:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._config.provider_timeout_seconds)
        try:
            token_response = await client.post(
                self._config.oidc_token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._config.oidc_redirect_uri,
                    "client_id": self._config.oidc_client_id,
                    "client_secret": self._config.oidc_client_secret,
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            id_token = token_payload.get("id_token") if isinstance(token_payload, dict) else None
            if not isinstance(id_token, str):
                raise OIDCProviderError("Identity provider response did not include an ID token")
            jwks_response = await client.get(self._config.oidc_jwks_uri, headers={"Accept": "application/json"})
            jwks_response.raise_for_status()
            claims = self._validate_id_token(id_token, jwks_response.json(), nonce)
        except OIDCProviderError:
            raise
        except (httpx.HTTPError, ValueError, jwt.PyJWTError) as exc:
            raise OIDCProviderError("Enterprise identity validation failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        email = str(claims.get("email") or "").strip().lower()
        subject = str(claims.get("sub") or "").strip()
        if not email or not subject or claims.get("email_verified") is False:
            raise OIDCProviderError("Identity provider did not return a verified email identity")
        username = str(claims.get("preferred_username") or email.split("@", 1)[0]).strip().lower()
        return OIDCIdentity(subject=subject, email=email, username=username)

    def _validate_id_token(self, encoded: str, jwks: dict[str, Any], nonce: str) -> dict[str, Any]:
        header = jwt.get_unverified_header(encoded)
        if header.get("alg") not in {"RS256", "ES256"}:
            raise OIDCProviderError("Identity provider used an unsupported signing algorithm")
        key_id = header.get("kid")
        key_set = jwt.PyJWKSet.from_dict(jwks)
        signing_key = next((key.key for key in key_set.keys if key.key_id == key_id), None)
        if signing_key is None:
            raise OIDCProviderError("Identity provider signing key was not found")
        claims = jwt.decode(
            encoded,
            signing_key,
            algorithms=[header["alg"]],
            audience=self._config.oidc_client_id,
            issuer=self._config.oidc_issuer,
            options={"require": ["sub", "iss", "aud", "exp", "iat", "nonce"]},
        )
        if claims.get("nonce") != nonce:
            raise OIDCProviderError("Identity provider nonce validation failed")
        return claims


def allowed_email_domain(email: str, config: Settings = settings) -> bool:
    allowed = {item.strip().lower() for item in config.oidc_allowed_email_domains.split(",") if item.strip()}
    return bool(allowed and "@" in email and email.rsplit("@", 1)[1].lower() in allowed)
