import hmac
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import Principal, authenticate_request, create_access_token, verify_password
from app.db import get_db
from app.models import AuditLog, User
from app.schemas import AuthConfiguration, TokenResponse, UserSummary
from app.services.oidc import OIDCClient, OIDCConfigurationError, OIDCProviderError, allowed_email_domain


auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


@auth_router.get("/config", response_model=AuthConfiguration)
async def auth_configuration() -> AuthConfiguration:
    try:
        OIDCClient()
        enabled = True
    except OIDCConfigurationError:
        enabled = False
    return AuthConfiguration(
        oidc_enabled=enabled,
        oidc_login_url="/api/v1/auth/oidc/login" if enabled else None,
    )


@auth_router.get("/oidc/login")
async def oidc_login() -> RedirectResponse:
    try:
        client = OIDCClient()
    except OIDCConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if len(settings.auth_jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    nonce = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    state = jwt.encode(
        {
            "typ": "oidc_state",
            "nonce": nonce,
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": settings.auth_issuer,
            "aud": "oidc-state",
        },
        settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
    )
    response = RedirectResponse(client.authorization_url(state=state, nonce=nonce), status_code=302)
    response.set_cookie(
        settings.oidc_state_cookie_name,
        state,
        max_age=600,
        httponly=True,
        secure=settings.environment.lower() not in {"development", "test"},
        samesite="lax",
        path="/api/v1/auth/oidc/callback",
    )
    return response


@auth_router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    cookie_state = request.cookies.get(settings.oidc_state_cookie_name)
    if not cookie_state or not hmac.compare_digest(cookie_state, state):
        raise HTTPException(status_code=401, detail="Invalid enterprise login state")
    try:
        state_claims = jwt.decode(
            state,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience="oidc-state",
            issuer=settings.auth_issuer,
            options={"require": ["typ", "nonce", "iat", "exp", "iss", "aud"]},
        )
        if state_claims.get("typ") != "oidc_state":
            raise jwt.InvalidTokenError("invalid state type")
        identity = await OIDCClient().exchange(code=code, nonce=state_claims["nonce"])
    except (jwt.PyJWTError, KeyError, OIDCConfigurationError, OIDCProviderError) as exc:
        raise HTTPException(status_code=401, detail="Enterprise login validation failed") from exc

    allowed_domains_configured = bool(settings.oidc_allowed_email_domains.strip())
    if allowed_domains_configured and not allowed_email_domain(identity.email):
        raise HTTPException(status_code=403, detail="Enterprise email domain is not permitted")
    result = await db.execute(select(User).where(func.lower(User.email) == identity.email))
    user = result.scalars().first()
    if user is None:
        if not settings.oidc_auto_provision or not allowed_email_domain(identity.email):
            raise HTTPException(status_code=403, detail="Enterprise account has not been provisioned")
        username = re.sub(r"[^a-z0-9._-]", "-", identity.username)[:80] or "oidc-user"
        username_exists = await db.scalar(select(User.id).where(func.lower(User.username) == username))
        if username_exists:
            subject_suffix = hashlib.sha256(identity.subject.encode("utf-8")).hexdigest()[:12]
            username = f"{username[:64]}-{subject_suffix}"
        user = User(
            username=username,
            email=identity.email,
            role="reviewer",
            password_hash=f"!oidc:{identity.subject[:200]}",
            active=True,
        )
        db.add(user)
        await db.flush()
    if not user.active:
        raise HTTPException(status_code=401, detail="Enterprise account is inactive")
    db.add(
        AuditLog(
            entity_type="user",
            entity_id=user.id,
            action="oidc_login_completed",
            actor=user.username,
            details={"issuer": settings.oidc_issuer},
        )
    )
    await db.commit()
    token, expires_in = create_access_token(user)
    response = RedirectResponse(settings.oidc_frontend_redirect_url, status_code=302)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=expires_in,
        httponly=True,
        secure=settings.environment.lower() not in {"development", "test"},
        samesite="strict",
        path="/",
    )
    response.delete_cookie(settings.oidc_state_cookie_name, path="/api/v1/auth/oidc/callback")
    return response


@auth_router.post("/token", response_model=TokenResponse)
async def issue_token(
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    identity = form.username.strip().lower()
    result = await db.execute(
        select(User).where(
            or_(func.lower(User.username) == identity, func.lower(User.email) == identity)
        )
    )
    user = result.scalars().first()
    if not user or not user.active or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(user)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=expires_in,
        httponly=True,
        secure=settings.environment.lower() not in {"development", "test"},
        samesite="strict",
        path="/",
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@auth_router.get("/me", response_model=UserSummary)
async def get_me(
    principal: Principal = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    result = await db.execute(select(User).where(User.id == principal.user_id))
    user = result.scalar_one()
    return UserSummary.model_validate(user)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    principal: Principal = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(select(User).where(User.id == principal.user_id))
    user = result.scalar_one()
    user.token_version += 1
    await db.commit()
    response.delete_cookie(key=settings.auth_cookie_name, path="/", httponly=True, samesite="strict")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
