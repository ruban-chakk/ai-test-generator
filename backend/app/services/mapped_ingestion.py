from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, TextIO

from app.services.file_ingestion import ParsedRequirement
from app.services.historical_ingestion import ParsedHistoricalStep, ParsedHistoricalTestCase


class MappedIngestionError(ValueError):
    """Raised when a mapping profile or source document cannot be safely transformed."""


@dataclass(frozen=True)
class MappedBatch:
    entity_type: Literal["requirement", "test_case"]
    source_record_count: int
    items: tuple[ParsedRequirement | ParsedHistoricalTestCase, ...]
    issues: tuple[dict[str, Any], ...]


REQUIREMENT_FIELDS = {"external_id", "title", "description"}
TEST_CASE_FIELDS = {
    "external_id", "requirement_external_id", "scenario_external_id", "scenario_title",
    "scenario_description", "title", "description", "prerequisite", "priority", "severity",
    "category", "type", "status", "version", "approved_at", "approved_by", "steps",
}
ALLOWED_TRANSFORMS = {
    "string", "integer", "version_integer", "iso_datetime", "excel_datetime",
    "references", "numbered_steps", "lower", "upper",
}
CUSTOM_FIELD_TYPES = {"auto", "string", "integer", "number", "boolean", "date", "datetime", "list", "json"}


def validate_mapping_configuration(entity_type: str, configuration: dict[str, Any]) -> None:
    if entity_type not in {"requirement", "test_case"}:
        raise MappedIngestionError("entity_type must be requirement or test_case")
    fields = configuration.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise MappedIngestionError("configuration.fields must be a non-empty object")
    allowed = REQUIREMENT_FIELDS if entity_type == "requirement" else TEST_CASE_FIELDS
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise MappedIngestionError("Unsupported canonical fields: " + ", ".join(unknown))
    required = REQUIREMENT_FIELDS if entity_type == "requirement" else {
        "external_id", "requirement_external_id", "title", "description", "priority", "severity", "steps"
    }
    missing = sorted(required - set(fields))
    if missing:
        raise MappedIngestionError("Missing canonical field mappings: " + ", ".join(missing))
    for target, raw_rule in fields.items():
        rule = _rule(raw_rule)
        transform = rule.get("transform", "string")
        if transform not in ALLOWED_TRANSFORMS:
            raise MappedIngestionError(f"Field {target} uses unsupported transform {transform}")
        if not rule.get("source") and not rule.get("sources") and "default" not in rule:
            raise MappedIngestionError(f"Field {target} requires source, sources, or default")
    custom = configuration.get("custom_fields", {})
    if not isinstance(custom, dict):
        raise MappedIngestionError("configuration.custom_fields must be an object")
    for name, raw_rule in custom.items():
        if not isinstance(name, str) or not name.strip():
            raise MappedIngestionError("Custom field names must be non-empty strings")
        rule = _custom_rule(raw_rule)
        if not rule.get("source"):
            raise MappedIngestionError(f"Custom field {name} requires a source path")
        if rule.get("type", "auto") not in CUSTOM_FIELD_TYPES:
            raise MappedIngestionError(f"Custom field {name} uses an unsupported type")
        if "allowed_values" in rule and not isinstance(rule["allowed_values"], list):
            raise MappedIngestionError(f"Custom field {name} allowed_values must be an array")
        if "semantic_weight" in rule and rule["semantic_weight"] not in {0, 1, 2, 3}:
            raise MappedIngestionError(f"Custom field {name} semantic_weight must be 0, 1, 2, or 3")
        if "pattern" in rule:
            try:
                re.compile(str(rule["pattern"]))
            except re.error as exc:
                raise MappedIngestionError(f"Custom field {name} has an invalid validation pattern") from exc
    options = configuration.get("options", {})
    if not isinstance(options, dict):
        raise MappedIngestionError("configuration.options must be an object")
    if options.get("multi_requirement_strategy", "reject") not in {"reject", "first", "duplicate"}:
        raise MappedIngestionError("multi_requirement_strategy must be reject, first, or duplicate")
    if options.get("unresolved_reference_policy", "reject") not in {"reject", "skip"}:
        raise MappedIngestionError("unresolved_reference_policy must be reject or skip")
    existing_strategy = options.get("existing_record_strategy", "skip")
    allowed_existing = {"skip", "update", "reject"} if entity_type == "requirement" else {
        "skip", "new_version", "reject"
    }
    if existing_strategy not in allowed_existing:
        raise MappedIngestionError(
            "existing_record_strategy must be " + ", ".join(sorted(allowed_existing))
        )


def map_import_file(
    filename: str | None,
    content: bytes,
    *,
    entity_type: Literal["requirement", "test_case"],
    configuration: dict[str, Any],
    max_bytes: int,
    max_records: int,
) -> MappedBatch:
    validate_mapping_configuration(entity_type, configuration)
    name = Path(filename or "import.json").name.strip()
    extension = Path(name).suffix.lower()
    if extension not in {".json", ".csv"}:
        raise MappedIngestionError("Mapped imports support UTF-8 JSON and CSV files")
    if not content:
        raise MappedIngestionError("The uploaded file is empty")
    if len(content) > max_bytes:
        raise MappedIngestionError(f"The uploaded file exceeds the {max_bytes}-byte mapped-import limit")
    if b"\x00" in content:
        raise MappedIngestionError("Binary files are not accepted")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MappedIngestionError("The uploaded file must be UTF-8 text") from exc
    records = _load_records(text, extension, configuration.get("record_path"))
    if len(records) > max_records:
        raise MappedIngestionError(f"The source exceeds the {max_records}-record mapped-import limit")
    digest = hashlib.sha256(content).hexdigest()
    return map_import_records(
        records,
        entity_type=entity_type,
        configuration=configuration,
        filename=name,
        digest=digest,
        start_row=1,
        max_records=max_records,
    )


def map_import_records(
    records: Iterable[dict[str, Any]],
    *,
    entity_type: Literal["requirement", "test_case"],
    configuration: dict[str, Any],
    filename: str,
    digest: str,
    start_row: int = 1,
    max_records: int,
) -> MappedBatch:
    validate_mapping_configuration(entity_type, configuration)
    issues: list[dict[str, Any]] = []
    items: list[ParsedRequirement | ParsedHistoricalTestCase] = []
    source_count = 0
    for row_number, record in enumerate(records, start=start_row):
        source_count += 1
        if source_count > max_records:
            raise MappedIngestionError(f"The batch exceeds the {max_records}-record mapped-import limit")
        if not isinstance(record, dict):
            issues.append({"row": row_number, "severity": "error", "message": "Source record must be an object"})
            continue
        try:
            mapped = _map_record(record, configuration, issues, row_number)
            custom_fields, custom_schema = _map_custom_fields(record, configuration.get("custom_fields", {}))
            if entity_type == "requirement":
                items.append(_requirement(mapped, custom_fields, custom_schema, filename, digest, row_number))
            else:
                items.extend(
                    _test_cases(
                        mapped,
                        custom_fields,
                        custom_schema,
                        filename,
                        digest,
                        row_number,
                        configuration,
                        issues,
                    )
                )
        except (TypeError, ValueError) as exc:
            issues.append({"row": row_number, "severity": "error", "message": str(exc)})
    if len(items) > max_records:
        raise MappedIngestionError(
            f"Mapping expansion produced {len(items)} records, exceeding the {max_records}-record limit"
        )
    return MappedBatch(
        entity_type=entity_type,
        source_record_count=source_count,
        items=tuple(items),
        issues=tuple(issues),
    )


def iter_source_records(stream: TextIO, extension: str) -> Iterator[dict[str, Any]]:
    """Stream top-level JSON arrays, NDJSON, or CSV without materializing the file."""

    if extension == ".csv":
        for record in csv.DictReader(stream):
            yield dict(record)
        return
    if extension not in {".json", ".jsonl", ".ndjson"}:
        raise MappedIngestionError("Streamed mapped imports support JSON, JSONL, NDJSON, and CSV")
    if extension in {".jsonl", ".ndjson"}:
        for row_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MappedIngestionError(f"Invalid JSON object at source line {row_number}") from exc
            if not isinstance(value, dict):
                raise MappedIngestionError(f"Source line {row_number} must contain a JSON object")
            yield value
        return
    yield from _iter_json_array(stream)


def _iter_json_array(stream: TextIO) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    started = False
    eof = False
    while True:
        if position > 1_000_000:
            buffer = buffer[position:]
            position = 0
        while position >= len(buffer) and not eof:
            chunk = stream.read(64 * 1024)
            if chunk:
                buffer += chunk
            else:
                eof = True
        while position < len(buffer) and buffer[position].isspace():
            position += 1
        if not started:
            if position < len(buffer) and buffer[position] == "\ufeff":
                position += 1
                continue
            if position >= len(buffer):
                raise MappedIngestionError("The JSON source is empty")
            if buffer[position] != "[":
                raise MappedIngestionError("Streamed JSON imports require a top-level array")
            position += 1
            started = True
            continue
        while position < len(buffer) and (buffer[position].isspace() or buffer[position] == ","):
            position += 1
        if position < len(buffer) and buffer[position] == "]":
            return
        if position >= len(buffer):
            if eof:
                raise MappedIngestionError("The JSON array is incomplete")
            continue
        try:
            value, next_position = decoder.raw_decode(buffer, position)
        except json.JSONDecodeError as exc:
            if eof:
                raise MappedIngestionError("The JSON array contains an invalid record") from exc
            chunk = stream.read(64 * 1024)
            if chunk:
                buffer += chunk
                continue
            eof = True
            continue
        if not isinstance(value, dict):
            raise MappedIngestionError("Every streamed JSON array item must be an object")
        position = next_position
        yield value


def _load_records(text: str, extension: str, record_path: str | None) -> list[dict[str, Any]]:
    if extension == ".csv":
        records: Any = list(csv.DictReader(io.StringIO(text)))
    else:
        try:
            records = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MappedIngestionError("The JSON file is invalid") from exc
        if record_path:
            records = _get_path(records, record_path)
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise MappedIngestionError("The configured record path must resolve to an array of objects")
    return records


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split(".") if path else []:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _rule(value: Any) -> dict[str, Any]:
    return {"source": value} if isinstance(value, str) else dict(value or {})


def _custom_rule(value: Any) -> dict[str, Any]:
    return {"source": value, "type": "auto", "index": True, "semantic_weight": 1} if isinstance(value, str) else {
        "type": "auto",
        "index": True,
        "semantic_weight": 1,
        **dict(value or {}),
    }


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _map_custom_fields(
    record: dict[str, Any],
    configuration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    values: dict[str, Any] = {}
    schema: dict[str, Any] = {}
    for name, raw_rule in configuration.items():
        rule = _custom_rule(raw_rule)
        raw_value = _get_path(record, str(rule["source"]))
        if not _present(raw_value):
            if "default" in rule:
                raw_value = rule["default"]
            elif rule.get("required"):
                raise ValueError(f"Required custom field {name} is missing")
            else:
                continue
        value = _coerce_custom_value(raw_value, rule.get("type", "auto"), name)
        allowed = rule.get("allowed_values")
        if allowed is not None and value not in allowed:
            raise ValueError(f"Custom field {name} must be one of {allowed}")
        if isinstance(value, str):
            if rule.get("pattern") and not re.fullmatch(str(rule["pattern"]), value):
                raise ValueError(f"Custom field {name} does not match its validation pattern")
            if "min_length" in rule and len(value) < int(rule["min_length"]):
                raise ValueError(f"Custom field {name} is shorter than min_length")
            if "max_length" in rule and len(value) > int(rule["max_length"]):
                raise ValueError(f"Custom field {name} exceeds max_length")
        values[name] = value
        schema[name] = {
            key: rule[key]
            for key in ("type", "required", "allowed_values", "index", "semantic_weight")
            if key in rule
        }
    return values, schema


def _coerce_custom_value(value: Any, field_type: str, name: str) -> Any:
    try:
        if field_type == "auto":
            return value
        if field_type == "string":
            return str(value).strip()
        if field_type == "integer":
            return int(value)
        if field_type == "number":
            return float(value)
        if field_type == "boolean":
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
            raise ValueError
        if field_type in {"date", "datetime"}:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.date().isoformat() if field_type == "date" else parsed.isoformat()
        if field_type == "list":
            if isinstance(value, list):
                return value
            return [item.strip() for item in str(value).split(",") if item.strip()]
        if field_type == "json":
            return value if isinstance(value, (dict, list)) else json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Custom field {name} cannot be converted to {field_type}") from exc
    raise ValueError(f"Custom field {name} uses unsupported type {field_type}")


def _map_record(record: dict[str, Any], configuration: dict[str, Any], issues: list[dict], row: int) -> dict:
    result: dict[str, Any] = {}
    for target, raw_rule in configuration["fields"].items():
        rule = _rule(raw_rule)
        if rule.get("sources"):
            values = [_get_path(record, path) for path in rule["sources"]]
            value = rule.get("separator", "\n").join(str(item).strip() for item in values if _present(item))
        else:
            value = _get_path(record, rule.get("source", "")) if rule.get("source") else rule.get("default")
        if not _present(value) and "default" in rule:
            value = rule["default"]
        result[target] = _transform(value, rule.get("transform", "string"), record, configuration, issues, row)
    return result


def _transform(value: Any, transform: str, record: dict, configuration: dict, issues: list[dict], row: int) -> Any:
    if transform == "string":
        return "" if value is None else str(value).strip()
    if transform == "lower":
        return str(value or "").strip().lower()
    if transform == "upper":
        return str(value or "").strip().upper()
    if transform == "integer":
        return int(value)
    if transform == "version_integer":
        match = re.search(r"\d+", str(value or ""))
        if not match:
            raise ValueError(f"Cannot derive a version integer from {value!r}")
        return max(1, int(match.group()))
    if transform == "iso_datetime":
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(tzinfo=None)
    if transform == "excel_datetime":
        return (datetime(1899, 12, 30, tzinfo=UTC) + timedelta(days=float(value))).replace(tzinfo=None)
    if transform == "references":
        return re.findall(r"[A-Za-z][A-Za-z0-9_]*-\d+", str(value or ""))
    if transform == "numbered_steps":
        expected_path = configuration.get("options", {}).get("expected_result_source")
        expected = _get_path(record, expected_path) if expected_path else ""
        return _numbered_steps(value, expected, issues, row)
    raise ValueError(f"Unsupported transform {transform}")


def _numbered_steps(value: Any, expected: Any, issues: list[dict], row: int) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    lines = [line.strip() for line in re.split(r"[\r\n]+", str(value or "")) if line.strip()]
    actions = [re.sub(r"^\s*\d+\s*[.)-]?\s*", "", line).strip() for line in lines]
    if not actions:
        raise ValueError("Mapped test case requires at least one step")
    expected_lines = [line.strip() for line in re.split(r"[\r\n]+", str(expected or "")) if line.strip()]
    if len(expected_lines) != len(actions):
        issues.append({
            "row": row,
            "severity": "warning",
            "message": "Per-step expected results were unavailable; intermediate expectations were generated",
        })
    return [
        {
            "step_number": index,
            "action": action,
            "expected_result": (
                expected_lines[index - 1]
                if len(expected_lines) == len(actions)
                else (str(expected).strip() if index == len(actions) else "Step completes successfully.")
            ),
        }
        for index, action in enumerate(actions, start=1)
    ]


def _required(mapped: dict[str, Any], field: str) -> str:
    value = str(mapped.get(field) or "").strip()
    if not value:
        raise ValueError(f"Mapped record is missing required field {field}")
    return value


def _requirement(
    mapped: dict,
    custom: dict,
    custom_schema: dict,
    filename: str,
    digest: str,
    row: int,
) -> ParsedRequirement:
    return ParsedRequirement(
        external_id=_required(mapped, "external_id"),
        title=_required(mapped, "title"),
        description=_required(mapped, "description"),
        metadata={
            "upload_filename": filename,
            "upload_sha256": digest,
            "upload_row": row,
            "custom_fields": custom,
            "custom_field_schema": custom_schema,
        },
    )


def _test_cases(
    mapped: dict, custom: dict, custom_schema: dict, filename: str, digest: str, row: int,
    configuration: dict, issues: list[dict],
) -> list[ParsedHistoricalTestCase]:
    refs = mapped.get("requirement_external_id")
    refs = refs if isinstance(refs, list) else [str(refs or "").strip()]
    refs = [item for item in refs if item]
    strategy = configuration.get("options", {}).get("multi_requirement_strategy", "reject")
    if not refs:
        raise ValueError("Mapped test case has no requirement reference")
    if len(refs) > 1 and strategy == "reject":
        raise ValueError("Mapped test case has multiple requirement references")
    if strategy == "first":
        refs = refs[:1]
    steps = mapped.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Mapped test case requires a non-empty steps array")
    scenario_id = str(mapped.get("scenario_external_id") or mapped.get("category") or "imported").strip()
    scenario_title = str(mapped.get("scenario_title") or mapped.get("category") or "Imported scenario").strip()
    scenario_description = str(mapped.get("scenario_description") or scenario_title).strip()
    approved_at = mapped.get("approved_at")
    if not isinstance(approved_at, datetime):
        approved_at = datetime.now(UTC).replace(tzinfo=None)
    status = str(mapped.get("status") or "approved").lower()
    if status not in {"approved", "deprecated"}:
        raise ValueError("Mapped status must be approved or deprecated")
    return [
        ParsedHistoricalTestCase(
            external_id=_required(mapped, "external_id"),
            requirement_external_id=ref,
            scenario_external_id=scenario_id,
            scenario_title=scenario_title,
            scenario_description=scenario_description,
            title=_required(mapped, "title"),
            description=_required(mapped, "description"),
            prerequisite=str(mapped.get("prerequisite") or "").strip() or None,
            priority=_required(mapped, "priority"),
            severity=_required(mapped, "severity"),
            category=str(mapped.get("category") or "").strip() or None,
            test_type=str(mapped.get("type") or "").strip() or None,
            status=status,
            version=int(mapped.get("version") or 1),
            approved_at=approved_at,
            source_approved_by=str(mapped.get("approved_by") or "").strip() or None,
            steps=tuple(
                ParsedHistoricalStep(
                    step_number=int(step.get("step_number", index)),
                    action=str(step.get("action") or "").strip(),
                    expected_result=str(step.get("expected_result") or "").strip(),
                )
                for index, step in enumerate(steps, start=1)
            ),
            upload_filename=filename,
            upload_sha256=digest,
            upload_row=row,
            custom_fields=custom,
            custom_field_schema=custom_schema,
        )
        for ref in refs
    ]
