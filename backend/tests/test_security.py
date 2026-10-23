import asyncio
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import settings
from app.core.security import (
    authenticate_request,
    create_access_token,
    hash_password,
    require_global_role,
    verify_password,
)
from app.models import User


class FakeScalars:
    def __init__(self, user: User | None) -> None:
        self._user = user

    def first(self) -> User | None:
        return self._user


class FakeResult:
    def __init__(self, user: User | None) -> None:
        self._user = user

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._user)


class FakeSession:
    def __init__(self, user: User | None) -> None:
        self._user = user

    async def execute(self, _statement: object) -> FakeResult:
        return FakeResult(self._user)


def make_request(
    *,
    method: str = "GET",
    cookie: str | None = None,
    origin: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie:
        headers.append((b"cookie", f"{settings.auth_cookie_name}={cookie}".encode()))
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": method, "path": "/", "headers": headers})


@pytest.fixture
def auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "a-secure-test-secret-with-32-bytes-minimum")
    monkeypatch.setattr(settings, "auth_access_token_minutes", 5)


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        username="reviewer",
        email="reviewer@example.com",
        role="reviewer",
        password_hash="unused",
        active=True,
        token_version=1,
    )


def test_passwords_are_argon2_hashed_and_verified() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect password", encoded)


def test_access_token_is_checked_against_current_database_user(auth_settings: None) -> None:
    user = make_user()
    token, expires_in = create_access_token(user)

    async def authenticate_and_authorize() -> None:
        principal = await authenticate_request(make_request(), token, FakeSession(user))
        assert principal.user_id == user.id
        assert principal.role == "reviewer"
        with pytest.raises(HTTPException) as exc_info:
            require_global_role("admin")
        assert exc_info.value.status_code == 403

    asyncio.run(authenticate_and_authorize())
    assert expires_in == 300


def test_token_version_change_revokes_existing_token(auth_settings: None) -> None:
    user = make_user()
    token, _ = create_access_token(user)
    user.token_version += 1

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(authenticate_request(make_request(), token, FakeSession(user)))

    assert exc_info.value.status_code == 401


def test_cookie_authenticated_write_rejects_untrusted_origin(auth_settings: None) -> None:
    user = make_user()
    token, _ = create_access_token(user)
    request = make_request(method="POST", cookie=token, origin="https://attacker.example")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(authenticate_request(request, None, FakeSession(user)))

    assert exc_info.value.status_code == 403
