import csv
import io
import json

import pytest

from app.services.historical_ingestion import (
    HistoricalIngestionError,
    parse_historical_test_case_file,
)


def valid_case(**overrides):
    value = {
        "external_id": "TC-101",
        "requirement_external_id": "REQ-10",
        "scenario_external_id": "SC-10",
        "scenario_title": "Password reset links",
        "scenario_description": "Validate secure password reset link handling.",
        "title": "Reject an expired reset link",
        "description": "The expired link must be rejected without changing credentials.",
        "priority": "high",
        "severity": "major",
        "category": "security",
        "type": "regression",
        "status": "approved",
        "version": 3,
        "approved_at": "2025-01-02T03:04:05Z",
        "approved_by": "legacy-reviewer",
        "steps": [
            {
                "step_number": 1,
                "action": "Open an expired password reset link.",
                "expected_result": "The application rejects the expired link.",
            }
        ],
    }
    value.update(overrides)
    return value


def test_parses_json_and_normalizes_historical_case() -> None:
    content = json.dumps({"test_cases": [valid_case()]}).encode()
    parsed = parse_historical_test_case_file(
        "legacy-cases.json",
        content,
        max_bytes=100_000,
        max_test_cases=10,
    )
    assert len(parsed) == 1
    assert parsed[0].external_id == "TC-101"
    assert parsed[0].version == 3
    assert parsed[0].approved_at.isoformat() == "2025-01-02T03:04:05"
    assert parsed[0].steps[0].expected_result.endswith("expired link.")
    assert len(parsed[0].upload_sha256) == 64


def test_parses_csv_with_json_steps() -> None:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(valid_case()))
    writer.writeheader()
    row = valid_case()
    row["steps"] = json.dumps(row["steps"])
    writer.writerow(row)
    parsed = parse_historical_test_case_file(
        "legacy-cases.csv",
        output.getvalue().encode(),
        max_bytes=100_000,
        max_test_cases=10,
    )
    assert parsed[0].scenario_external_id == "SC-10"
    assert parsed[0].steps[0].step_number == 1


def test_rejects_duplicate_case_identity_and_conflicting_scenario() -> None:
    duplicate = json.dumps([valid_case(), valid_case()]).encode()
    with pytest.raises(HistoricalIngestionError, match="duplicates external_id"):
        parse_historical_test_case_file(
            "legacy.json", duplicate, max_bytes=100_000, max_test_cases=10
        )

    conflict = json.dumps(
        [
            valid_case(),
            valid_case(external_id="TC-102", scenario_title="Conflicting title"),
        ]
    ).encode()
    with pytest.raises(HistoricalIngestionError, match="conflicts with another definition"):
        parse_historical_test_case_file(
            "legacy.json", conflict, max_bytes=100_000, max_test_cases=10
        )


def test_rejects_ambiguous_timestamp_and_duplicate_steps() -> None:
    ambiguous = json.dumps([valid_case(approved_at="2025-01-02T03:04:05")]).encode()
    with pytest.raises(HistoricalIngestionError, match="include a timezone"):
        parse_historical_test_case_file(
            "legacy.json", ambiguous, max_bytes=100_000, max_test_cases=10
        )

    duplicate_steps = valid_case()
    duplicate_steps["steps"] = [duplicate_steps["steps"][0], duplicate_steps["steps"][0]]
    with pytest.raises(HistoricalIngestionError, match="duplicate step number"):
        parse_historical_test_case_file(
            "legacy.json",
            json.dumps([duplicate_steps]).encode(),
            max_bytes=100_000,
            max_test_cases=10,
        )
