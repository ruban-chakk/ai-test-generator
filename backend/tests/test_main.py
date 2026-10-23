from datetime import datetime, timedelta, timezone

from app.api.routes import _as_utc_naive
from app.main import app


def test_application_registers_health_auth_and_rate_limited_api_routes() -> None:
    paths = set(app.openapi()["paths"])
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/auth/token" in paths
    assert "/api/v1/executions" in paths
    assert "/api/v1/operations/alerts" in paths


def test_compliance_export_dates_normalize_timezone_qualified_values_to_utc_naive() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    value = datetime(2026, 1, 1, 5, 30, tzinfo=ist)

    assert _as_utc_naive(value) == datetime(2026, 1, 1)
    assert _as_utc_naive(value).tzinfo is None
