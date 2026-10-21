from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FileIngestionError(ValueError):
    """Raised when an uploaded requirement document is unsafe or invalid."""


@dataclass(frozen=True)
class ParsedRequirement:
    external_id: str
    title: str
    description: str
    metadata: dict[str, Any]


ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json"}


def safe_filename(filename: str | None) -> str:
    value = Path(filename or "requirements.txt").name.strip()
    if not value or value in {".", ".."}:
        raise FileIngestionError("A valid filename is required")
    return value[:255]


def parse_requirement_file(
    filename: str | None,
    content: bytes,
    *,
    max_bytes: int,
    max_requirements: int,
) -> list[ParsedRequirement]:
    name = safe_filename(filename)
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileIngestionError("Supported file types are .txt, .md, .csv, and .json")
    if not content:
        raise FileIngestionError("The uploaded file is empty")
    if len(content) > max_bytes:
        raise FileIngestionError(f"The uploaded file exceeds the {max_bytes}-byte limit")
    if b"\x00" in content:
        raise FileIngestionError("Binary files are not accepted")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileIngestionError("The uploaded file must be UTF-8 text") from exc

    digest = hashlib.sha256(content).hexdigest()
    if extension in {".txt", ".md"}:
        rows = [_parse_text(name, text)]
    elif extension == ".csv":
        rows = _parse_csv(text)
    else:
        rows = _parse_json(text)

    if not rows:
        raise FileIngestionError("The uploaded file contains no requirements")
    if len(rows) > max_requirements:
        raise FileIngestionError(f"The uploaded file exceeds the {max_requirements}-requirement limit")

    parsed: list[ParsedRequirement] = []
    for index, row in enumerate(rows, start=1):
        title = _required_text(row.get("title"), "title", index, 500)
        description = _required_text(row.get("description"), "description", index, 100_000)
        external_id = _optional_text(row.get("external_id"), 255) or f"file:{digest[:24]}:{index}"
        parsed.append(
            ParsedRequirement(
                external_id=external_id,
                title=title,
                description=description,
                metadata={
                    "upload_filename": name,
                    "upload_sha256": digest,
                    "upload_row": index,
                },
            )
        )
    return parsed


def _parse_text(filename: str, text: str) -> dict[str, str]:
    stripped = text.strip()
    if not stripped:
        return {}
    lines = stripped.splitlines()
    first = lines[0].strip().lstrip("#").strip()
    first_is_title = bool(first and len(first) <= 500)
    title = first if first_is_title else Path(filename).stem.replace("_", " ").replace("-", " ")
    description = "\n".join(lines[1:]).strip() if first_is_title else stripped
    return {"title": title, "description": description or stripped}


def _parse_csv(text: str) -> list[dict[str, Any]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not {"title", "description"}.issubset(
            {field.strip().lower() for field in reader.fieldnames if field}
        ):
            raise FileIngestionError("CSV files require title and description columns")
        return [{str(key).strip().lower(): value for key, value in row.items() if key} for row in reader]
    except csv.Error as exc:
        raise FileIngestionError("The CSV file is invalid") from exc


def _parse_json(text: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileIngestionError("The JSON file is invalid") from exc
    if isinstance(value, dict) and "requirements" in value:
        value = value["requirements"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise FileIngestionError("JSON must be a requirement object, an array, or an object with a requirements array")
    return value


def _required_text(value: Any, field: str, row: int, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise FileIngestionError(f"Requirement {row} is missing {field}")
    if len(text) > maximum:
        raise FileIngestionError(f"Requirement {row} {field} exceeds {maximum} characters")
    return text


def _optional_text(value: Any, maximum: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > maximum:
        raise FileIngestionError(f"external_id exceeds {maximum} characters")
    return text
