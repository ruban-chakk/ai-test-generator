from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class HistoricalIngestionError(ValueError):
    """Raised when a historical test-case export is unsafe or invalid."""


@dataclass(frozen=True)
class ParsedHistoricalStep:
    step_number: int
    action: str
    expected_result: str


@dataclass(frozen=True)
class ParsedHistoricalTestCase:
    external_id: str
    requirement_external_id: str
    scenario_external_id: str
    scenario_title: str
    scenario_description: str
    title: str
    description: str
    prerequisite: str | None
    priority: str
    severity: str
    category: str | None
    test_type: str | None
    status: str
    version: int
    approved_at: datetime
    source_approved_by: str | None
    steps: tuple[ParsedHistoricalStep, ...]
    upload_filename: str
    upload_sha256: str
    upload_row: int
    custom_fields: dict[str, Any] = field(default_factory=dict)
    custom_field_schema: dict[str, Any] = field(default_factory=dict)


ALLOWED_EXTENSIONS = {".json", ".csv"}
ALLOWED_STATUSES = {"approved", "deprecated"}


def parse_historical_test_case_file(
    filename: str | None,
    content: bytes,
    *,
    max_bytes: int,
    max_test_cases: int,
) -> list[ParsedHistoricalTestCase]:
    name = Path(filename or "historical-test-cases.json").name.strip()
    if not name or name in {".", ".."}:
        raise HistoricalIngestionError("A valid filename is required")
    name = name[:255]
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HistoricalIngestionError("Historical test-case imports support .json and .csv files")
    if not content:
        raise HistoricalIngestionError("The uploaded file is empty")
    if len(content) > max_bytes:
        raise HistoricalIngestionError(f"The uploaded file exceeds the {max_bytes}-byte limit")
    if b"\x00" in content:
        raise HistoricalIngestionError("Binary files are not accepted")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HistoricalIngestionError("The uploaded file must be UTF-8 text") from exc

    rows = _parse_json(text) if extension == ".json" else _parse_csv(text)
    if not rows:
        raise HistoricalIngestionError("The uploaded file contains no test cases")
    if len(rows) > max_test_cases:
        raise HistoricalIngestionError(
            f"The uploaded file exceeds the {max_test_cases}-test-case limit"
        )

    digest = hashlib.sha256(content).hexdigest()
    parsed = [
        _parse_row(row, row_number=index, filename=name, digest=digest)
        for index, row in enumerate(rows, start=1)
    ]
    identities: set[tuple[str, str]] = set()
    scenarios: dict[tuple[str, str], tuple[str, str]] = {}
    for item in parsed:
        identity = (item.requirement_external_id, item.external_id)
        if identity in identities:
            raise HistoricalIngestionError(
                f"Historical test case {item.upload_row} duplicates external_id {item.external_id} "
                f"for requirement {item.requirement_external_id}"
            )
        identities.add(identity)
        scenario_identity = (item.requirement_external_id, item.scenario_external_id)
        scenario_content = (item.scenario_title, item.scenario_description)
        if scenario_identity in scenarios and scenarios[scenario_identity] != scenario_content:
            raise HistoricalIngestionError(
                f"Historical test case {item.upload_row} conflicts with another definition of scenario "
                f"{item.scenario_external_id}"
            )
        scenarios[scenario_identity] = scenario_content
    return parsed


def _parse_json(text: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HistoricalIngestionError("The JSON file is invalid") from exc
    if isinstance(value, dict) and "test_cases" in value:
        value = value["test_cases"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise HistoricalIngestionError(
            "JSON must be a test-case object, an array, or an object with a test_cases array"
        )
    return value


def _parse_csv(text: str) -> list[dict[str, Any]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HistoricalIngestionError("The CSV file requires a header row")
        rows = [
            {str(key).strip().lower(): value for key, value in row.items() if key}
            for row in reader
        ]
    except csv.Error as exc:
        raise HistoricalIngestionError("The CSV file is invalid") from exc
    for index, row in enumerate(rows, start=1):
        steps = row.get("steps")
        try:
            row["steps"] = json.loads(steps) if isinstance(steps, str) else steps
        except json.JSONDecodeError as exc:
            raise HistoricalIngestionError(
                f"Historical test case {index} steps must be a JSON array"
            ) from exc
    return rows


def _parse_row(
    row: dict[str, Any],
    *,
    row_number: int,
    filename: str,
    digest: str,
) -> ParsedHistoricalTestCase:
    steps_value = row.get("steps")
    if not isinstance(steps_value, list) or not steps_value:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} requires a non-empty steps array"
        )
    steps: list[ParsedHistoricalStep] = []
    seen_numbers: set[int] = set()
    for step_index, step in enumerate(steps_value, start=1):
        if not isinstance(step, dict):
            raise HistoricalIngestionError(
                f"Historical test case {row_number} step {step_index} must be an object"
            )
        number = _positive_integer(step.get("step_number", step_index), "step_number", row_number)
        if number in seen_numbers:
            raise HistoricalIngestionError(
                f"Historical test case {row_number} contains duplicate step number {number}"
            )
        seen_numbers.add(number)
        steps.append(
            ParsedHistoricalStep(
                step_number=number,
                action=_required_text(step.get("action"), "step action", row_number, 20_000),
                expected_result=_required_text(
                    step.get("expected_result"),
                    "step expected_result",
                    row_number,
                    20_000,
                ),
            )
        )

    status = _optional_text(row.get("status"), 32) or "approved"
    if status not in ALLOWED_STATUSES:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} status must be approved or deprecated"
        )
    approved_at = _parse_datetime(row.get("approved_at"), row_number)
    return ParsedHistoricalTestCase(
        external_id=_required_text(row.get("external_id"), "external_id", row_number, 255),
        requirement_external_id=_required_text(
            row.get("requirement_external_id"),
            "requirement_external_id",
            row_number,
            255,
        ),
        scenario_external_id=_required_text(
            row.get("scenario_external_id"),
            "scenario_external_id",
            row_number,
            255,
        ),
        scenario_title=_required_text(row.get("scenario_title"), "scenario_title", row_number, 500),
        scenario_description=_required_text(
            row.get("scenario_description"),
            "scenario_description",
            row_number,
            100_000,
        ),
        title=_required_text(row.get("title"), "title", row_number, 500),
        description=_required_text(row.get("description"), "description", row_number, 100_000),
        prerequisite=_optional_text(row.get("prerequisite"), 20_000),
        priority=_required_text(row.get("priority"), "priority", row_number, 64),
        severity=_required_text(row.get("severity"), "severity", row_number, 64),
        category=_optional_text(row.get("category"), 128),
        test_type=_optional_text(row.get("type"), 128),
        status=status,
        version=_positive_integer(row.get("version", 1), "version", row_number),
        approved_at=approved_at,
        source_approved_by=_optional_text(row.get("approved_by"), 255),
        steps=tuple(sorted(steps, key=lambda item: item.step_number)),
        upload_filename=filename,
        upload_sha256=digest,
        upload_row=row_number,
    )


def _parse_datetime(value: Any, row_number: int) -> datetime:
    if value in {None, ""}:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} is missing approved_at"
        )
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} approved_at must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} approved_at must include a timezone"
        )
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _required_text(value: Any, field: str, row_number: int, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise HistoricalIngestionError(f"Historical test case {row_number} is missing {field}")
    if len(text) > maximum:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} {field} exceeds {maximum} characters"
        )
    return text


def _optional_text(value: Any, maximum: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > maximum:
        raise HistoricalIngestionError(f"A text value exceeds {maximum} characters")
    return text


def _positive_integer(value: Any, field: str, row_number: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} {field} must be a positive integer"
        ) from exc
    if parsed < 1:
        raise HistoricalIngestionError(
            f"Historical test case {row_number} {field} must be a positive integer"
        )
    return parsed
