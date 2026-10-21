from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.models import Alert, OutboxEvent


ALERT_DELIVERY_REQUESTED = "alert.delivery_requested"


class AlertDeliveryConfigurationError(RuntimeError):
    """Raised when outbound alert delivery is not configured."""


class AlertDeliveryProviderError(RuntimeError):
    """Raised when the alert receiver cannot accept a notification."""


async def create_alert(
    db: AsyncSession,
    *,
    dedupe_key: str,
    category: str,
    severity: str,
    title: str,
    details: dict[str, Any],
    project_id: uuid.UUID | None = None,
    config: Settings = settings,
) -> Alert:
    configured = bool(config.alert_webhook_url and config.alert_webhook_token)
    alert_id = uuid.uuid4()
    created_at = datetime.now(UTC).replace(tzinfo=None)
    inserted_id = await db.scalar(
        insert(Alert)
        .values(
            id=alert_id,
            project_id=project_id,
            dedupe_key=dedupe_key,
            category=category,
            severity=severity,
            title=title,
            details=details,
            status="open",
            delivery_status="pending" if configured else "not_configured",
            created_at=created_at,
        )
        .on_conflict_do_nothing(index_elements=[Alert.dedupe_key])
        .returning(Alert.id)
    )
    if inserted_id is None:
        existing = await db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key))
        if existing is None:
            raise RuntimeError("alert deduplication did not return a durable record")
        return existing
    alert = await db.get(Alert, inserted_id)
    if alert is None:
        raise RuntimeError("inserted alert could not be reloaded")
    if configured:
        db.add(
            OutboxEvent(
                event_key=f"alert.delivery:{alert.id}",
                event_type=ALERT_DELIVERY_REQUESTED,
                aggregate_type="alert",
                aggregate_id=alert.id,
                payload={"schema_version": 1},
                status="pending",
            )
        )
    return alert


class AlertWebhookClient:
    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.alert_webhook_url or not config.alert_webhook_token:
            raise AlertDeliveryConfigurationError("ALERT_WEBHOOK_URL and ALERT_WEBHOOK_TOKEN are required")
        self._url = config.alert_webhook_url
        self._token = config.alert_webhook_token
        self._timeout = config.alert_webhook_timeout_seconds
        self._client = client

    async def deliver(self, alert: Alert, *, idempotency_key: str) -> None:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        payload = {
            "id": str(alert.id),
            "project_id": str(alert.project_id) if alert.project_id else None,
            "category": alert.category,
            "severity": alert.severity,
            "title": alert.title,
            "details": alert.details,
            "created_at": alert.created_at.replace(tzinfo=UTC).isoformat()
            if alert.created_at.tzinfo is None
            else alert.created_at.isoformat(),
        }
        try:
            for attempt in range(1, 4):
                try:
                    response = await client.post(
                        self._url,
                        headers={
                            "Authorization": f"Bearer {self._token}",
                            "Content-Type": "application/json",
                            "Idempotency-Key": idempotency_key,
                        },
                        json=payload,
                    )
                    if (response.status_code == 429 or response.status_code >= 500) and attempt < 3:
                        await asyncio.sleep(min(2 ** (attempt - 1), 4))
                        continue
                    response.raise_for_status()
                    return
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= 3:
                        raise AlertDeliveryProviderError("Alert delivery failed after 3 attempts") from exc
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                except httpx.HTTPStatusError as exc:
                    raise AlertDeliveryProviderError(
                        f"Alert receiver returned {exc.response.status_code} response"
                    ) from exc
        finally:
            if owns_client:
                await client.aclose()
        raise AlertDeliveryProviderError("Alert delivery did not complete")
