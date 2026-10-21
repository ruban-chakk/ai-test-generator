import asyncio
import json
import uuid
from datetime import datetime

import httpx
import pytest

from app.core.config import Settings
from app.models import Alert
from app.services.alerts import AlertDeliveryConfigurationError, AlertWebhookClient as WebhookClient


def test_alert_webhook_sends_sanitized_idempotent_notification() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(204)

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            alert_webhook_url="https://alerts.example/hooks/platform",
            alert_webhook_token="alert-secret",
        )
        alert = Alert(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            dedupe_key="execution-failed:1",
            category="test_execution_failed",
            severity="high",
            title="Execution failed",
            details={"execution_run_id": "run-1"},
            status="open",
            delivery_status="pending",
            created_at=datetime(2026, 10, 21, 12, 0, 0),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await WebhookClient(config, client).deliver(alert, idempotency_key="alert.delivery:1")
        request = captured["request"]
        assert isinstance(request, httpx.Request)
        assert request.headers["Authorization"] == "Bearer alert-secret"
        assert request.headers["Idempotency-Key"] == "alert.delivery:1"
        assert captured["payload"]["category"] == "test_execution_failed"  # type: ignore[index]
        assert "dedupe_key" not in captured["payload"]  # type: ignore[operator]

    asyncio.run(scenario())


def test_alert_webhook_fails_closed_without_configuration() -> None:
    with pytest.raises(AlertDeliveryConfigurationError):
        WebhookClient(Settings(_env_file=None))
