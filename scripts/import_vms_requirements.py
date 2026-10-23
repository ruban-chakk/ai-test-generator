#!/usr/bin/env python3
"""Import markdown requirement catalogs into the AI Test Generator API."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ID_HEADERS = {"id", "use case id", "requirement id", "test case id", "rule id", "suite id"}
TITLE_HEADERS = {
    "title",
    "requirement",
    "goal",
    "rule",
    "area",
    "module",
    "business rule",
    "scenario",
    "test objective",
    "action",
    "workflow",
    "field",
    "login type",
}
DESCRIPTION_HEADERS = {
    "description",
    "acceptance criteria",
    "qa expectation",
    "validation focus",
    "main success outcome",
    "alternate/negative paths",
    "business value",
    "preconditions",
    "expected result",
}
SECTION_ID_PATTERN = re.compile(r"^(?P<id>[A-Z]{2,6}(?:-[A-Z]+)?-\d{3})\s+[-:]\s+(?P<title>.+)$")


@dataclass(frozen=True)
class Candidate:
    external_id: str
    title: str
    description: str
    source: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Folder containing markdown requirement files.")
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000/api/v1",
        help="AI Test Generator API base URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report candidates without creating requirements.",
    )
    parser.add_argument(
        "--project-name",
        default="VMS",
        help="Project name to assign imported requirements to.",
    )
    return parser.parse_args()


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip().replace("<br>", "\n") for cell in line.split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_markdown_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def iter_tables(lines: list[str]) -> Iterable[tuple[int, list[str], list[list[str]]]]:
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.lstrip().startswith("|"):
            index += 1
            continue

        start = index
        table_lines: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            table_lines.append(lines[index])
            index += 1

        if len(table_lines) < 3 or not is_separator_row(table_lines[1]):
            continue

        headers = [header.strip() for header in split_markdown_row(table_lines[0])]
        rows = [
            split_markdown_row(row)
            for row in table_lines[2:]
            if row.strip() and not is_separator_row(row)
        ]
        yield start + 1, headers, rows


def normalize_header(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


def clean_text(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def choose_title(row: dict[str, str], external_id: str) -> str:
    for header in TITLE_HEADERS:
        value = clean_text(row.get(header, ""))
        if value:
            return f"{external_id} - {value}"[:240]

    for header, value in row.items():
        if header not in ID_HEADERS and clean_text(value):
            return f"{external_id} - {clean_text(value)}"[:240]

    return external_id


def build_description(row: dict[str, str], file_title: str, table_line: int) -> str:
    parts = [f"Imported from {file_title}, table starting at line {table_line}."]
    for header, value in row.items():
        value = clean_text(value)
        if value:
            label = header[:1].upper() + header[1:]
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def candidates_from_tables(path: Path, lines: list[str]) -> list[Candidate]:
    candidates: list[Candidate] = []
    source = f"vms_requirements:{path.stem}"

    for table_line, raw_headers, raw_rows in iter_tables(lines):
        normalized_headers = [normalize_header(header) for header in raw_headers]
        id_index = next(
            (index for index, header in enumerate(normalized_headers) if header in ID_HEADERS),
            None,
        )

        if id_index is None:
            continue

        for row_number, raw_row in enumerate(raw_rows, start=1):
            row_values = raw_row + [""] * max(0, len(normalized_headers) - len(raw_row))
            row = dict(zip(normalized_headers, row_values))
            external_id = clean_text(row_values[id_index]) if id_index < len(row_values) else ""

            if not external_id or external_id.lower() in {"id", "n/a", "-"}:
                continue

            title = choose_title(row, external_id)
            description = build_description(row, path.name, table_line)
            candidates.append(
                Candidate(
                    external_id=external_id,
                    title=title,
                    description=description,
                    source=source,
                )
            )

    return candidates


def candidates_from_sections(path: Path, lines: list[str]) -> list[Candidate]:
    candidates: list[Candidate] = []
    source = f"vms_requirements:{path.stem}"
    current: tuple[str, str, int] | None = None
    body: list[str] = []

    def flush() -> None:
        if not current or not body:
            return
        external_id, title, line_number = current
        text = "\n".join(line.strip() for line in body if line.strip())
        if len(text) < 30:
            return
        description = f"Imported from {path.name}, section starting at line {line_number}.\n{text}"
        candidates.append(
            Candidate(
                external_id=external_id,
                title=f"{external_id} - {clean_text(title)}"[:240],
                description=description,
                source=source,
            )
        )

    for index, line in enumerate(lines, start=1):
        heading = line.lstrip("#").strip() if line.startswith("#") else ""
        match = SECTION_ID_PATTERN.match(heading)
        if match:
            flush()
            current = (match.group("id"), match.group("title"), index)
            body = []
            continue
        if current:
            if line.startswith("#"):
                flush()
                current = None
                body = []
            else:
                body.append(line)

    flush()
    return candidates


def extract_candidates(folder: Path) -> list[Candidate]:
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for path in sorted(folder.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for candidate in [*candidates_from_tables(path, lines), *candidates_from_sections(path, lines)]:
            key = candidate.external_id.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def api_json(method: str, url: str, payload: dict | None = None) -> object:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def existing_external_ids(api_base_url: str) -> set[str]:
    requirements_url = urljoin(api_base_url.rstrip("/") + "/", "requirements")
    requirements = api_json("GET", requirements_url)
    if not isinstance(requirements, list):
        raise RuntimeError("Unexpected response from requirements API.")
    return {
        str(requirement.get("external_id", "")).strip().lower()
        for requirement in requirements
        if isinstance(requirement, dict) and requirement.get("external_id")
    }


def ensure_project(api_base_url: str, project_name: str) -> str:
    projects_url = urljoin(api_base_url.rstrip("/") + "/", "projects")
    projects = api_json("GET", projects_url)
    if not isinstance(projects, list):
        raise RuntimeError("Unexpected response from projects API.")
    for project in projects:
        if isinstance(project, dict) and str(project.get("name", "")).lower() == project_name.lower():
            return str(project["id"])

    project = api_json(
        "POST",
        projects_url,
        {
            "name": project_name,
            "description": f"Requirements imported from {project_name} documentation.",
            "status": "active",
        },
    )
    if not isinstance(project, dict) or not project.get("id"):
        raise RuntimeError("Unexpected response while creating project.")
    return str(project["id"])


def create_requirement(api_base_url: str, candidate: Candidate, project_id: str) -> None:
    requirements_url = urljoin(api_base_url.rstrip("/") + "/", "requirements")
    payload = {
        "project_id": project_id,
        "external_id": candidate.external_id,
        "title": candidate.title,
        "description": candidate.description,
        "source": candidate.source,
    }
    api_json("POST", requirements_url, payload)


def main() -> int:
    args = parse_args()
    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        print(f"Requirement folder not found: {folder}", file=sys.stderr)
        return 2

    candidates = extract_candidates(folder)
    print(f"Parsed {len(candidates)} requirement candidates from {folder}")

    if args.dry_run:
        for candidate in candidates[:20]:
            print(f"- {candidate.external_id}: {candidate.title}")
        if len(candidates) > 20:
            print(f"... {len(candidates) - 20} more")
        return 0

    try:
        existing_ids = existing_external_ids(args.api_base_url)
        project_id = ensure_project(args.api_base_url, args.project_name.strip() or "VMS")
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"Unable to prepare import through {args.api_base_url}: {exc}", file=sys.stderr)
        return 1

    created = 0
    skipped = 0
    errors: list[str] = []
    for candidate in candidates:
        key = candidate.external_id.strip().lower()
        if key in existing_ids:
            skipped += 1
            continue
        try:
            create_requirement(args.api_base_url, candidate, project_id)
            existing_ids.add(key)
            created += 1
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{candidate.external_id}: HTTP {exc.code} {details}")
        except (URLError, TimeoutError) as exc:
            errors.append(f"{candidate.external_id}: {exc}")

    print(f"Created: {created}")
    print(f"Skipped existing: {skipped}")
    print(f"Errors: {len(errors)}")
    for error in errors[:20]:
        print(f"- {error}", file=sys.stderr)
    if len(errors) > 20:
        print(f"... {len(errors) - 20} more errors", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
