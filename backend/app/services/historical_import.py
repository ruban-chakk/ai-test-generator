from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ApprovalRecord,
    AuditLog,
    IntegrationRun,
    Requirement,
    TestCase,
    TestCaseStep,
    TestCaseVersion,
    TestScenario,
)
from app.services.historical_ingestion import ParsedHistoricalTestCase
from app.services.outbox import (
    TEST_CASE_INDEX_REQUESTED,
    TEST_CASE_VERSION_INDEX_REQUESTED,
    enqueue_index_event,
)


class HistoricalImportConflictError(ValueError):
    """Raised when an external identity already exists with different canonical content."""


@dataclass(frozen=True)
class HistoricalImportResult:
    run_id: uuid.UUID | None
    parsed_count: int
    created_scenario_count: int
    created_test_case_count: int
    updated_test_case_count: int
    existing_test_case_count: int
    queued_vector_count: int


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _step_payload(item: ParsedHistoricalTestCase) -> list[dict]:
    return [
        {
            "step_number": step.step_number,
            "action": step.action,
            "expected_result": step.expected_result,
        }
        for step in item.steps
    ]


def _existing_step_payload(test_case: TestCase) -> list[dict]:
    return [
        {
            "step_number": step.step_number,
            "action": step.action,
            "expected_result": step.expected_result,
        }
        for step in sorted(test_case.steps, key=lambda value: value.step_number)
    ]


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _case_matches(test_case: TestCase, item: ParsedHistoricalTestCase, scenario_id: uuid.UUID) -> bool:
    return (
        test_case.scenario_id == scenario_id
        and test_case.title == item.title
        and test_case.description == item.description
        and test_case.prerequisite == item.prerequisite
        and test_case.priority == item.priority
        and test_case.severity == item.severity
        and test_case.category == item.category
        and test_case.type == item.test_type
        and test_case.status == item.status
        and test_case.version == item.version
        and _naive_utc(test_case.approved_at) == _naive_utc(item.approved_at)
        and _existing_step_payload(test_case) == _step_payload(item)
        and (test_case.custom_fields_json or {}) == item.custom_fields
        and (test_case.custom_field_schema_json or {}) == item.custom_field_schema
    )


async def import_historical_test_cases(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    items: list[ParsedHistoricalTestCase],
    actor: str,
    existing_record_strategy: str = "reject",
    record_run: bool = True,
    commit: bool = True,
) -> HistoricalImportResult:
    if not items:
        raise ValueError("At least one historical test case is required")
    if existing_record_strategy not in {"skip", "new_version", "reject"}:
        raise ValueError("existing_record_strategy must be skip, new_version, or reject")

    requirement_external_ids = {item.requirement_external_id for item in items}
    requirements = list(
        (
            await db.execute(
                select(Requirement).where(
                    Requirement.project_id == project_id,
                    Requirement.external_id.in_(requirement_external_ids),
                ).with_for_update()
            )
        )
        .scalars()
        .all()
    )
    requirement_by_external_id = {
        requirement.external_id: requirement
        for requirement in requirements
        if requirement.external_id
    }
    missing_requirements = sorted(requirement_external_ids - set(requirement_by_external_id))
    if missing_requirements:
        raise HistoricalImportConflictError(
            "Requirements must be imported first; missing external IDs: "
            + ", ".join(missing_requirements[:20])
        )

    requirement_ids = [requirement.id for requirement in requirements]
    existing_scenarios = list(
        (
            await db.execute(
                select(TestScenario).where(TestScenario.requirement_id.in_(requirement_ids))
            )
        )
        .scalars()
        .all()
    )
    scenario_by_identity = {
        (scenario.requirement_id, scenario.external_id): scenario
        for scenario in existing_scenarios
        if scenario.external_id
    }
    existing_cases = list(
        (
            await db.execute(
                select(TestCase)
                .where(
                    TestCase.requirement_id.in_(requirement_ids),
                    TestCase.external_id.is_not(None),
                )
                .options(selectinload(TestCase.steps))
            )
        )
        .scalars()
        .all()
    )
    case_by_identity = {
        (test_case.requirement_id, test_case.external_id): test_case
        for test_case in existing_cases
        if test_case.external_id
    }

    # Validate every pre-existing identity before adding anything to the session.
    for item in items:
        requirement = requirement_by_external_id[item.requirement_external_id]
        scenario = scenario_by_identity.get((requirement.id, item.scenario_external_id))
        scenario_differs = scenario and (
            scenario.title != item.scenario_title
            or scenario.description != item.scenario_description
        )
        test_case = case_by_identity.get((requirement.id, item.external_id))
        if scenario_differs and not (
            existing_record_strategy == "new_version"
            or (test_case and existing_record_strategy == "skip")
        ):
            raise HistoricalImportConflictError(
                f"Scenario {item.scenario_external_id} already exists with different content"
            )
        if test_case:
            matches = scenario is not None and _case_matches(test_case, item, scenario.id)
            if not matches and existing_record_strategy == "reject":
                raise HistoricalImportConflictError(
                    f"Test case {item.external_id} already exists with different content"
                )

    created_scenario_count = 0
    created_test_case_count = 0
    updated_test_case_count = 0
    existing_test_case_count = 0
    queued_vector_count = 0
    for item in items:
        requirement = requirement_by_external_id[item.requirement_external_id]
        scenario_identity = (requirement.id, item.scenario_external_id)
        scenario = scenario_by_identity.get(scenario_identity)
        if scenario is None:
            scenario = TestScenario(
                requirement_id=requirement.id,
                external_id=item.scenario_external_id,
                title=item.scenario_title,
                description=item.scenario_description,
                status="approved",
                version=1,
            )
            db.add(scenario)
            await db.flush()
            scenario_by_identity[scenario_identity] = scenario
            created_scenario_count += 1
        elif (
            existing_record_strategy == "new_version"
            and (scenario.title != item.scenario_title or scenario.description != item.scenario_description)
        ):
            scenario.title = item.scenario_title
            scenario.description = item.scenario_description
            scenario.status = "approved"
            scenario.version += 1

        identity = (requirement.id, item.external_id)
        existing_case = case_by_identity.get(identity)
        if existing_case and _case_matches(existing_case, item, scenario.id):
            existing_test_case_count += 1
            continue
        if existing_case and existing_record_strategy == "skip":
            existing_test_case_count += 1
            continue
        if existing_case and existing_record_strategy == "new_version":
            next_version = max(item.version, existing_case.version + 1)
            vector_id = f"test_case:{existing_case.id}:v{next_version}"
            existing_case.scenario_id = scenario.id
            existing_case.title = item.title
            existing_case.description = item.description
            existing_case.prerequisite = item.prerequisite
            existing_case.priority = item.priority
            existing_case.severity = item.severity
            existing_case.category = item.category
            existing_case.type = item.test_type
            existing_case.status = item.status
            existing_case.version = next_version
            existing_case.approved_at = item.approved_at
            existing_case.locked = True
            existing_case.repository_status = "pending_index"
            existing_case.repository_synced_at = None
            existing_case.vector_id = vector_id
            existing_case.custom_fields_json = item.custom_fields
            existing_case.custom_field_schema_json = item.custom_field_schema
            await db.execute(delete(TestCaseStep).where(TestCaseStep.test_case_id == existing_case.id))
            for step in item.steps:
                db.add(
                    TestCaseStep(
                        test_case_id=existing_case.id,
                        step_number=step.step_number,
                        action=step.action,
                        expected_result=step.expected_result,
                    )
                )
            version = TestCaseVersion(
                test_case_id=existing_case.id,
                requirement_id=requirement.id,
                scenario_id=scenario.id,
                version=next_version,
                external_id=item.external_id,
                source="historical_import",
                title=item.title,
                description=item.description,
                prerequisite=item.prerequisite,
                priority=item.priority,
                severity=item.severity,
                category=item.category,
                type=item.test_type,
                status=item.status,
                approved_by=item.source_approved_by or actor,
                approved_at=item.approved_at,
                notes=f"Updated by {actor} from {item.upload_filename}",
                steps_snapshot=_step_payload(item),
                vector_id=vector_id,
                custom_fields_json=item.custom_fields,
                custom_field_schema_json=item.custom_field_schema,
            )
            db.add(version)
            await db.flush()
            db.add(
                ApprovalRecord(
                    target_level="test_case",
                    target_id=existing_case.id,
                    approved_by=actor,
                    approved_at=_utcnow(),
                    version=next_version,
                    status=item.status,
                    notes=f"Historical update from {item.upload_filename}",
                )
            )
            enqueue_index_event(
                db,
                event_key=f"test_case_version.index:{version.id}",
                event_type=TEST_CASE_VERSION_INDEX_REQUESTED,
                aggregate_type="test_case_version",
                aggregate_id=version.id,
                payload={"test_case_id": str(existing_case.id), "version": next_version},
            )
            enqueue_index_event(
                db,
                event_key=(
                    f"test_case.current_index:{existing_case.id}:v{next_version}:"
                    f"{existing_case.status}"
                ),
                event_type=TEST_CASE_INDEX_REQUESTED,
                aggregate_type="test_case",
                aggregate_id=existing_case.id,
                payload={"version": next_version, "status": existing_case.status, "artifact_scope": "current"},
            )
            updated_test_case_count += 1
            queued_vector_count += 2
            continue

        test_case_id = uuid.uuid4()
        vector_id = f"test_case:{test_case_id}:v{item.version}"
        test_case = TestCase(
            id=test_case_id,
            scenario_id=scenario.id,
            requirement_id=requirement.id,
            external_id=item.external_id,
            source="historical_import",
            title=item.title,
            description=item.description,
            prerequisite=item.prerequisite,
            priority=item.priority,
            severity=item.severity,
            category=item.category,
            type=item.test_type,
            status=item.status,
            version=item.version,
            approved_at=item.approved_at,
            locked=True,
            repository_status="pending_index",
            vector_id=vector_id,
            custom_fields_json=item.custom_fields,
            custom_field_schema_json=item.custom_field_schema,
        )
        db.add(test_case)
        await db.flush()
        for step in item.steps:
            db.add(
                TestCaseStep(
                    test_case_id=test_case.id,
                    step_number=step.step_number,
                    action=step.action,
                    expected_result=step.expected_result,
                )
            )
        version = TestCaseVersion(
            test_case_id=test_case.id,
            requirement_id=requirement.id,
            scenario_id=scenario.id,
            version=item.version,
            external_id=item.external_id,
            source="historical_import",
            title=item.title,
            description=item.description,
            prerequisite=item.prerequisite,
            priority=item.priority,
            severity=item.severity,
            category=item.category,
            type=item.test_type,
            status=item.status,
            approved_by=item.source_approved_by or actor,
            approved_at=item.approved_at,
            notes=f"Imported by {actor} from {item.upload_filename}",
            steps_snapshot=_step_payload(item),
            vector_id=vector_id,
            custom_fields_json=item.custom_fields,
            custom_field_schema_json=item.custom_field_schema,
        )
        db.add(version)
        await db.flush()
        db.add(
            ApprovalRecord(
                target_level="test_case",
                target_id=test_case.id,
                approved_by=actor,
                approved_at=_utcnow(),
                version=item.version,
                status=item.status,
                notes=(
                    f"Historical import from {item.upload_filename}; source approver: "
                    f"{item.source_approved_by or 'not supplied'}"
                ),
            )
        )
        enqueue_index_event(
            db,
            event_key=f"test_case_version.index:{version.id}",
            event_type=TEST_CASE_VERSION_INDEX_REQUESTED,
            aggregate_type="test_case_version",
            aggregate_id=version.id,
            payload={"test_case_id": str(test_case.id), "version": item.version},
        )
        enqueue_index_event(
            db,
            event_key=(
                f"test_case.current_index:{test_case.id}:v{item.version}:"
                f"{test_case.status}"
            ),
            event_type=TEST_CASE_INDEX_REQUESTED,
            aggregate_type="test_case",
            aggregate_id=test_case.id,
            payload={"version": item.version, "status": test_case.status, "artifact_scope": "current"},
        )
        case_by_identity[identity] = test_case
        created_test_case_count += 1
        queued_vector_count += 2

    run_id: uuid.UUID | None = None
    if record_run:
        now = _utcnow()
        first = items[0]
        run = IntegrationRun(
            integration_type="historical_test_case_import",
            status="completed",
            requested_by=actor,
            parameters={
                "project_id": str(project_id),
                "filename": first.upload_filename,
                "sha256": first.upload_sha256,
            },
            result={
                "parsed_count": len(items),
                "created_scenario_count": created_scenario_count,
                "created_test_case_count": created_test_case_count,
                "updated_test_case_count": updated_test_case_count,
                "existing_test_case_count": existing_test_case_count,
                "queued_vector_count": queued_vector_count,
            },
            completed_at=now,
        )
        db.add(run)
        await db.flush()
        run_id = run.id
        db.add(
            AuditLog(
                entity_type="integration",
                entity_id=run.id,
                action="historical_test_cases_imported",
                actor=actor,
                details={
                    "project_id": str(project_id),
                    "sha256": first.upload_sha256,
                    "created_test_case_count": created_test_case_count,
                    "updated_test_case_count": updated_test_case_count,
                    "existing_test_case_count": existing_test_case_count,
                    "queued_vector_count": queued_vector_count,
                },
            )
        )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return HistoricalImportResult(
        run_id=run_id,
        parsed_count=len(items),
        created_scenario_count=created_scenario_count,
        created_test_case_count=created_test_case_count,
        updated_test_case_count=updated_test_case_count,
        existing_test_case_count=existing_test_case_count,
        queued_vector_count=queued_vector_count,
    )
