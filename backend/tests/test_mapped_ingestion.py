import json
from io import StringIO

import pytest

from app.services.mapped_ingestion import MappedIngestionError, iter_source_records, map_import_file


def test_maps_company_story_fields_and_preserves_custom_fields() -> None:
    configuration = {
        "fields": {
            "external_id": {"source": "key"},
            "title": {"source": "summary"},
            "description": {
                "sources": ["description", "acceptanceCriteria"],
                "separator": "\n\nAcceptance criteria:\n",
            },
        },
        "custom_fields": {
            "priority": {
                "source": "priority.name",
                "type": "string",
                "required": True,
                "allowed_values": ["P0", "P1", "P2"],
                "semantic_weight": 2,
            },
            "epic": "epic",
        },
        "options": {},
    }
    content = json.dumps([{
        "key": "HC-257",
        "summary": "Consultant dashboard",
        "description": "As a consultant, I need an inpatient dashboard.",
        "acceptanceCriteria": "Current inpatients are visible.",
        "priority": {"name": "P1"},
        "epic": "Emergency Management",
    }]).encode()

    batch = map_import_file(
        "stories.json", content, entity_type="requirement", configuration=configuration,
        max_bytes=10_000, max_records=100,
    )

    assert batch.source_record_count == 1
    assert len(batch.items) == 1
    item = batch.items[0]
    assert item.external_id == "HC-257"
    assert "Acceptance criteria" in item.description
    assert item.metadata["custom_fields"] == {"priority": "P1", "epic": "Emergency Management"}
    assert item.metadata["custom_field_schema"]["priority"]["semantic_weight"] == 2
    assert item.metadata["custom_field_schema"]["priority"]["type"] == "string"


def test_maps_numbered_steps_excel_dates_and_duplicate_story_links() -> None:
    configuration = {
        "fields": {
            "external_id": {"source": "id"},
            "requirement_external_id": {"source": "linkedStories", "transform": "references"},
            "scenario_external_id": {"source": "module"},
            "scenario_title": {"source": "module"},
            "scenario_description": {"source": "module"},
            "title": {"source": "title"},
            "description": {"source": "description"},
            "prerequisite": {"source": "preRequisites"},
            "priority": {"source": "priority"},
            "severity": {"source": "risk"},
            "category": {"source": "module"},
            "type": {"source": "type"},
            "status": {"default": "approved"},
            "version": {"source": "version", "transform": "version_integer"},
            "approved_at": {"source": "lastModifiedDate", "transform": "excel_datetime"},
            "approved_by": {"source": "createdBy"},
            "steps": {"source": "steps", "transform": "numbered_steps"},
        },
        "custom_fields": {"automation": "automationManual"},
        "options": {
            "expected_result_source": "expectedResults",
            "multi_requirement_strategy": "duplicate",
            "unresolved_reference_policy": "skip",
        },
    }
    content = json.dumps([{
        "module": "Registration",
        "id": "TC_005",
        "linkedStories": "HC-080, HC-153",
        "title": "Convert registration",
        "description": "Verify conversion.",
        "preRequisites": "PRN",
        "priority": "P1",
        "risk": "Critical",
        "type": "Integration",
        "version": "v7.0",
        "lastModifiedDate": 45176,
        "createdBy": "QA User",
        "automationManual": "Automated",
        "steps": "1. Open registration\n2. Convert to UHID",
        "expectedResults": "Conversion succeeds",
    }]).encode()

    batch = map_import_file(
        "testcases.json", content, entity_type="test_case", configuration=configuration,
        max_bytes=10_000, max_records=100,
    )

    assert len(batch.items) == 2
    assert {item.requirement_external_id for item in batch.items} == {"HC-080", "HC-153"}
    assert batch.items[0].version == 7
    assert len(batch.items[0].steps) == 2
    assert batch.items[0].steps[-1].expected_result == "Conversion succeeds"
    assert batch.items[0].custom_fields == {"automation": "Automated"}
    assert any(issue["severity"] == "warning" for issue in batch.issues)


def test_rejects_unknown_canonical_fields() -> None:
    with pytest.raises(MappedIngestionError, match="Unsupported canonical fields"):
        map_import_file(
            "stories.json",
            b'[{"key":"A","summary":"B","description":"C"}]',
            entity_type="requirement",
            configuration={
                "fields": {
                    "external_id": "key",
                    "title": "summary",
                    "description": "description",
                    "arbitrary_code": "payload",
                }
            },
            max_bytes=10_000,
            max_records=100,
        )


def test_typed_custom_field_validation_reports_bad_company_values() -> None:
    configuration = {
        "fields": {
            "external_id": "key",
            "title": "summary",
            "description": "description",
        },
        "custom_fields": {
            "risk_score": {"source": "risk", "type": "integer", "required": True},
            "owner": {"source": "owner", "type": "string", "pattern": r"[A-Z]{2,8}"},
        },
    }
    batch = map_import_file(
        "stories.json",
        b'[{"key":"A-1","summary":"Story","description":"Description","risk":"high","owner":"qa"}]',
        entity_type="requirement",
        configuration=configuration,
        max_bytes=10_000,
        max_records=100,
    )

    assert batch.items == ()
    assert batch.issues[0]["severity"] == "error"
    assert "risk_score" in batch.issues[0]["message"]


def test_streams_json_array_records_across_internal_read_boundaries() -> None:
    payload = json.dumps([
        {"key": "REQ-1", "description": "x" * 70_000},
        {"key": "REQ-2", "description": "small"},
    ])

    records = list(iter_source_records(StringIO(payload), ".json"))

    assert [record["key"] for record in records] == ["REQ-1", "REQ-2"]
    assert len(records[0]["description"]) == 70_000
