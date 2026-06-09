import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import (
    ApprovalRecord,
    AuditLog,
    Feedback,
    Requirement,
    TestCase,
    TestCaseStep as TestCaseStepModel,
    TestCaseVersion,
    TestScenario,
)
from app.schemas import (
    ApprovalAction,
    ApprovalRecordSummary,
    AuditLogSummary,
    FeedbackCreate,
    FeedbackSummary,
    RequirementCreate,
    RequirementDetail,
    TestCaseCreate,
    TestCaseStep,
    TestCaseStepCreate,
    TestCaseSummary,
    TestCaseVersionSummary,
    TestScenarioCreate,
    TestScenarioSummary,
    ValidationIssue,
    ValidationResult,
)

api_router = APIRouter()

TARGET_LEVELS = {"requirement", "scenario", "test_case"}


def _actor(payload: ApprovalAction) -> str:
    return payload.approved_by or "system"


def _step_snapshot(test_case: TestCase) -> list[dict]:
    return [
        {
            "step_number": step.step_number,
            "action": step.action,
            "expected_result": step.expected_result,
        }
        for step in sorted(test_case.steps or [], key=lambda item: item.step_number)
    ]


def _validate_test_case_content(test_case: TestCase) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(test_case.title.strip()) < 5:
        issues.append(ValidationIssue(field="title", message="Title must be descriptive."))
    if len(test_case.description.strip()) < 12:
        issues.append(ValidationIssue(field="description", message="Description must explain the behavior under test."))
    if not test_case.priority:
        issues.append(ValidationIssue(field="priority", message="Priority is required."))
    if not test_case.severity:
        issues.append(ValidationIssue(field="severity", message="Severity is required."))
    if not test_case.steps:
        issues.append(ValidationIssue(field="steps", message="At least one executable step is required."))

    seen_step_numbers: set[int] = set()
    for step in test_case.steps or []:
        if step.step_number in seen_step_numbers:
            issues.append(ValidationIssue(field="steps", message=f"Step {step.step_number} is duplicated."))
        seen_step_numbers.add(step.step_number)
        if len(step.action.strip()) < 8:
            issues.append(ValidationIssue(field="steps.action", message=f"Step {step.step_number} action is too short."))
        if len(step.expected_result.strip()) < 8:
            issues.append(
                ValidationIssue(
                    field="steps.expected_result",
                    message=f"Step {step.step_number} expected result is too short.",
                )
            )

    return issues


async def _create_test_case_version(
    db: AsyncSession,
    test_case: TestCase,
    approved_by: str,
    notes: str | None,
) -> None:
    version = TestCaseVersion(
        test_case_id=test_case.id,
        requirement_id=test_case.requirement_id,
        scenario_id=test_case.scenario_id,
        version=test_case.version,
        title=test_case.title,
        description=test_case.description,
        prerequisite=test_case.prerequisite,
        priority=test_case.priority,
        severity=test_case.severity,
        category=test_case.category,
        type=test_case.type,
        status=test_case.status,
        approved_by=approved_by,
        approved_at=test_case.approved_at or datetime.utcnow(),
        notes=notes,
        steps_snapshot=_step_snapshot(test_case),
    )
    db.add(version)


@api_router.get(
    "/requirements",
    response_model=list[RequirementDetail],
    tags=["Requirements"],
)
async def list_requirements(
    status: str | None = Query(None),
    source: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[RequirementDetail]:
    stmt = (
        select(Requirement)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
        .order_by(Requirement.updated_at.desc())
    )

    if status:
        stmt = stmt.where(Requirement.status == status)

    if source:
        stmt = stmt.where(Requirement.source == source)

    if search:
        search_term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Requirement.title.ilike(search_term),
                Requirement.description.ilike(search_term),
            )
        )

    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.post(
    "/requirements",
    response_model=RequirementDetail,
    tags=["Requirements"],
)
async def create_requirement(
    payload: RequirementCreate,
    db: AsyncSession = Depends(get_db),
) -> RequirementDetail:
    requirement = Requirement(
        external_id=payload.external_id,
        title=payload.title,
        description=payload.description,
        source=payload.source,
        status="draft",
    )
    db.add(requirement)
    await db.commit()
    await db.refresh(requirement)
    return requirement


@api_router.get(
    "/requirements/{requirement_id}",
    response_model=RequirementDetail,
    tags=["Requirements"],
)
async def get_requirement(
    requirement_id: str,
    db: AsyncSession = Depends(get_db),
) -> RequirementDetail:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")

    stmt = (
        select(Requirement)
        .where(Requirement.id == requirement_uuid)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
    )
    result = await db.execute(stmt)
    requirement = result.scalars().first()
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return requirement


async def _create_approval_record(
    db: AsyncSession,
    target_level: str,
    target_id: uuid.UUID,
    status: str,
    version: int,
    approved_by: str,
    notes: str | None = None,
) -> None:
    approval = ApprovalRecord(
        target_level=target_level,
        target_id=target_id,
        approved_by=approved_by,
        version=version,
        status=status,
        notes=notes,
    )
    db.add(approval)
    audit = AuditLog(
        entity_type=target_level,
        entity_id=target_id,
        action=f"{target_level}_{status}",
        actor=approved_by,
        details={"notes": notes, "version": version},
    )
    db.add(audit)


@api_router.post(
    "/requirements/{requirement_id}/approve",
    response_model=RequirementDetail,
    tags=["Approvals"],
)
async def approve_requirement(
    requirement_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> RequirementDetail:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")

    stmt = select(Requirement).where(Requirement.id == requirement_uuid)
    result = await db.execute(stmt)
    requirement = result.scalars().first()

    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if len(requirement.title.strip()) < 5 or len(requirement.description.strip()) < 12:
        raise HTTPException(status_code=422, detail="Requirement title and description must be reviewable before approval")

    requirement.status = "approved"
    await _create_approval_record(
        db,
        "requirement",
        requirement.id,
        "approved",
        1,
        _actor(payload),
        payload.notes,
    )
    await db.commit()

    stmt = (
        select(Requirement)
        .where(Requirement.id == requirement_uuid)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
    )
    result = await db.execute(stmt)
    requirement = result.scalars().first()
    return requirement


@api_router.post(
    "/requirements/{requirement_id}/reject",
    response_model=RequirementDetail,
    tags=["Approvals"],
)
async def reject_requirement(
    requirement_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> RequirementDetail:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")

    stmt = select(Requirement).where(Requirement.id == requirement_uuid)
    result = await db.execute(stmt)
    requirement = result.scalars().first()

    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    requirement.status = "reviewed"
    await _create_approval_record(
        db,
        "requirement",
        requirement.id,
        "rejected",
        1,
        _actor(payload),
        payload.notes,
    )
    await db.commit()

    stmt = (
        select(Requirement)
        .where(Requirement.id == requirement_uuid)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
    )
    result = await db.execute(stmt)
    requirement = result.scalars().first()
    return requirement


@api_router.post(
    "/scenarios/{scenario_id}/approve",
    response_model=TestScenarioSummary,
    tags=["Approvals"],
)
async def approve_scenario(
    scenario_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> TestScenarioSummary:
    try:
        scenario_uuid = uuid.UUID(scenario_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Scenario not found")

    stmt = (
        select(TestScenario)
        .where(TestScenario.id == scenario_uuid)
        .options(selectinload(TestScenario.test_cases).selectinload(TestCase.steps))
    )
    result = await db.execute(stmt)
    scenario = result.scalars().first()

    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    if len(scenario.title.strip()) < 5 or len(scenario.description.strip()) < 12:
        raise HTTPException(status_code=422, detail="Scenario title and description must be reviewable before approval")

    if scenario.status == "approved":
        scenario.version += 1
    scenario.status = "approved"
    await _create_approval_record(
        db,
        "scenario",
        scenario.id,
        "approved",
        scenario.version,
        _actor(payload),
        payload.notes,
    )
    await db.commit()
    await db.refresh(scenario)
    return scenario


@api_router.post(
    "/scenarios/{scenario_id}/reject",
    response_model=TestScenarioSummary,
    tags=["Approvals"],
)
async def reject_scenario(
    scenario_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> TestScenarioSummary:
    try:
        scenario_uuid = uuid.UUID(scenario_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Scenario not found")

    stmt = (
        select(TestScenario)
        .where(TestScenario.id == scenario_uuid)
        .options(selectinload(TestScenario.test_cases).selectinload(TestCase.steps))
    )
    result = await db.execute(stmt)
    scenario = result.scalars().first()

    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    scenario.status = "rejected"
    await _create_approval_record(
        db,
        "scenario",
        scenario.id,
        "rejected",
        scenario.version,
        _actor(payload),
        payload.notes,
    )
    await db.commit()
    await db.refresh(scenario)
    return scenario


@api_router.post(
    "/test_cases/{test_case_id}/approve",
    response_model=TestCaseSummary,
    tags=["Approvals"],
)
async def approve_test_case(
    test_case_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> TestCaseSummary:
    try:
        test_case_uuid = uuid.UUID(test_case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Test case not found")

    stmt = select(TestCase).where(TestCase.id == test_case_uuid).options(selectinload(TestCase.steps))
    result = await db.execute(stmt)
    test_case = result.scalars().first()

    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")

    issues = _validate_test_case_content(test_case)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={"message": "Test case failed governance validation", "issues": [issue.dict() for issue in issues]},
        )

    if test_case.status == "approved":
        test_case.version += 1
    test_case.status = "approved"
    test_case.approved_at = datetime.utcnow()
    test_case.locked = True
    test_case.repository_status = "active"
    test_case.repository_synced_at = datetime.utcnow()
    test_case.vector_id = test_case.vector_id or f"test_case:{test_case.id}:v{test_case.version}"
    actor = _actor(payload)
    await _create_test_case_version(db, test_case, actor, payload.notes)
    await _create_approval_record(
        db,
        "test_case",
        test_case.id,
        "approved",
        test_case.version,
        actor,
        payload.notes,
    )
    await db.commit()
    await db.refresh(test_case)
    return test_case


@api_router.post(
    "/test_cases/{test_case_id}/reject",
    response_model=TestCaseSummary,
    tags=["Approvals"],
)
async def reject_test_case(
    test_case_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> TestCaseSummary:
    try:
        test_case_uuid = uuid.UUID(test_case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Test case not found")

    stmt = select(TestCase).where(TestCase.id == test_case_uuid).options(selectinload(TestCase.steps))
    result = await db.execute(stmt)
    test_case = result.scalars().first()

    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")

    test_case.status = "rejected"
    test_case.repository_status = "rejected"
    await _create_approval_record(
        db,
        "test_case",
        test_case.id,
        "rejected",
        test_case.version,
        _actor(payload),
        payload.notes,
    )
    await db.commit()
    await db.refresh(test_case)
    return test_case


@api_router.post(
    "/feedback",
    response_model=FeedbackSummary,
    tags=["Feedback"],
)
async def create_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
) -> FeedbackSummary:
    if payload.target_level not in TARGET_LEVELS:
        raise HTTPException(status_code=422, detail="Feedback target level must be requirement, scenario, or test_case")
    if not payload.comment.strip():
        raise HTTPException(status_code=422, detail="Feedback comment is required")

    feedback = Feedback(
        target_level=payload.target_level,
        target_id=payload.target_id,
        source=payload.source,
        feedback_type=payload.feedback_type,
        comment=payload.comment,
        created_by=payload.created_by,
    )
    db.add(feedback)
    audit = AuditLog(
        entity_type="feedback",
        entity_id=feedback.id,
        action="feedback_created",
        actor=payload.created_by,
        details={
            "target_level": payload.target_level,
            "feedback_type": payload.feedback_type,
        },
    )
    db.add(audit)
    await db.commit()
    await db.refresh(feedback)
    return feedback


@api_router.get(
    "/feedback",
    response_model=list[FeedbackSummary],
    tags=["Feedback"],
)
async def list_feedback(
    target_level: str | None = Query(None),
    target_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[FeedbackSummary]:
    stmt = select(Feedback)
    if target_level:
        stmt = stmt.where(Feedback.target_level == target_level)
    if target_id:
        stmt = stmt.where(Feedback.target_id == target_id)
    stmt = stmt.order_by(Feedback.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/approvals",
    response_model=list[ApprovalRecordSummary],
    tags=["Approvals"],
)
async def list_approvals(
    target_level: str | None = Query(None),
    target_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRecordSummary]:
    stmt = select(ApprovalRecord)
    if target_level:
        stmt = stmt.where(ApprovalRecord.target_level == target_level)
    if target_id:
        stmt = stmt.where(ApprovalRecord.target_id == target_id)
    stmt = stmt.order_by(ApprovalRecord.approved_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/audit",
    response_model=list[AuditLogSummary],
    tags=["Audit"],
)
async def list_audit_logs(
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogSummary]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    stmt = stmt.order_by(AuditLog.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/test_cases/{test_case_id}/versions",
    response_model=list[TestCaseVersionSummary],
    tags=["TestCases"],
)
async def list_test_case_versions(
    test_case_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[TestCaseVersionSummary]:
    try:
        test_case_uuid = uuid.UUID(test_case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Test case not found")

    stmt = (
        select(TestCaseVersion)
        .where(TestCaseVersion.test_case_id == test_case_uuid)
        .order_by(TestCaseVersion.version.desc(), TestCaseVersion.approved_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/repository/test_cases",
    response_model=list[TestCaseSummary],
    tags=["Repository"],
)
async def list_repository_test_cases(
    status: str | None = Query("active"),
    db: AsyncSession = Depends(get_db),
) -> list[TestCaseSummary]:
    stmt = select(TestCase).options(selectinload(TestCase.steps)).order_by(TestCase.repository_synced_at.desc())
    if status:
        stmt = stmt.where(TestCase.repository_status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/validate/{target_level}/{target_id}",
    response_model=ValidationResult,
    tags=["Governance"],
)
async def validate_target(
    target_level: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
) -> ValidationResult:
    if target_level not in TARGET_LEVELS:
        raise HTTPException(status_code=422, detail="Target level must be requirement, scenario, or test_case")
    try:
        target_uuid = uuid.UUID(target_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Target not found")

    issues: list[ValidationIssue] = []
    if target_level == "requirement":
        result = await db.execute(select(Requirement).where(Requirement.id == target_uuid))
        requirement = result.scalars().first()
        if not requirement:
            raise HTTPException(status_code=404, detail="Requirement not found")
        if len(requirement.title.strip()) < 5:
            issues.append(ValidationIssue(field="title", message="Title must be descriptive."))
        if len(requirement.description.strip()) < 12:
            issues.append(ValidationIssue(field="description", message="Description must explain the requirement."))
    elif target_level == "scenario":
        result = await db.execute(select(TestScenario).where(TestScenario.id == target_uuid))
        scenario = result.scalars().first()
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")
        if len(scenario.title.strip()) < 5:
            issues.append(ValidationIssue(field="title", message="Title must be descriptive."))
        if len(scenario.description.strip()) < 12:
            issues.append(ValidationIssue(field="description", message="Description must explain the scenario."))
        if not scenario.priority:
            issues.append(ValidationIssue(field="priority", message="Priority is required."))
        if not scenario.severity:
            issues.append(ValidationIssue(field="severity", message="Severity is required."))
    else:
        result = await db.execute(
            select(TestCase).where(TestCase.id == target_uuid).options(selectinload(TestCase.steps))
        )
        test_case = result.scalars().first()
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        issues = _validate_test_case_content(test_case)

    return ValidationResult(valid=not issues, target_level=target_level, target_id=target_uuid, issues=issues)


@api_router.post(
    "/requirements/{requirement_id}/scenarios",
    response_model=TestScenarioSummary,
    tags=["Scenarios"],
)
async def create_scenario_for_requirement(
    requirement_id: str,
    payload: TestScenarioCreate,
    db: AsyncSession = Depends(get_db),
) -> TestScenarioSummary:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")

    stmt = select(Requirement).where(Requirement.id == requirement_uuid)
    result = await db.execute(stmt)
    requirement = result.scalars().first()

    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    scenario = TestScenario(
        requirement_id=requirement.id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        severity=payload.severity,
        category=payload.category,
        type=payload.type,
        status=payload.status or "draft",
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return scenario


@api_router.post(
    "/scenarios/{scenario_id}/test_cases",
    response_model=TestCaseSummary,
    tags=["TestCases"],
)
async def create_test_case_for_scenario(
    scenario_id: str,
    payload: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
) -> TestCaseSummary:
    try:
        scenario_uuid = uuid.UUID(scenario_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Scenario not found")

    stmt = select(TestScenario).where(TestScenario.id == scenario_uuid)
    result = await db.execute(stmt)
    scenario = result.scalars().first()

    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    test_case = TestCase(
        scenario_id=scenario.id,
        requirement_id=scenario.requirement_id,
        title=payload.title,
        description=payload.description,
        prerequisite=payload.prerequisite,
        priority=payload.priority,
        severity=payload.severity,
        category=payload.category,
        type=payload.type,
        status=payload.status or "draft",
    )
    db.add(test_case)
    await db.commit()
    
    # Refresh with eager loading of relationships
    stmt = select(TestCase).where(TestCase.id == test_case.id).options(selectinload(TestCase.steps))
    result = await db.execute(stmt)
    test_case = result.scalars().first()
    
    return test_case


@api_router.post(
    "/test_cases/{test_case_id}/steps",
    response_model=TestCaseStep,
    tags=["TestCases"],
)
async def append_test_case_step(
    test_case_id: str,
    payload: TestCaseStepCreate,
    db: AsyncSession = Depends(get_db),
) -> TestCaseStep:
    try:
        test_case_uuid = uuid.UUID(test_case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Test case not found")

    stmt = select(TestCase).where(TestCase.id == test_case_uuid)
    result = await db.execute(stmt)
    test_case = result.scalars().first()

    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")

    if test_case.locked:
        raise HTTPException(status_code=409, detail="Approved test cases are locked. Create a revision before changing steps.")

    step = TestCaseStepModel(
        test_case_id=test_case.id,
        step_number=payload.step_number,
        action=payload.action,
        expected_result=payload.expected_result,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


@api_router.post(
    "/requirements/{requirement_id}/generate",
    response_model=RequirementDetail,
    tags=["Requirements"],
)
async def generate_requirement_draft(
    requirement_id: str,
    db: AsyncSession = Depends(get_db),
) -> RequirementDetail:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")

    stmt = (
        select(Requirement)
        .where(Requirement.id == requirement_uuid)
        .options(selectinload(Requirement.scenarios))
    )
    result = await db.execute(stmt)
    requirement = result.scalars().first()

    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if requirement.scenarios:
        return requirement

    scenario = TestScenario(
        requirement_id=requirement.id,
        title=f"Validate: {requirement.title}",
        description=f"Generated scenario for requirement {requirement.external_id or requirement.title}.",
        priority="medium",
        severity="major",
        category="functional",
        type="regression",
        status="draft",
    )
    db.add(scenario)
    await db.flush()

    test_case = TestCase(
        scenario_id=scenario.id,
        requirement_id=requirement.id,
        title=f"Verify requirement: {requirement.title}",
        description="Generated test case for the requirement.",
        prerequisite="Requirement is defined and accessible.",
        priority="medium",
        severity="major",
        category="functional",
        type="regression",
        status="draft",
    )
    db.add(test_case)
    await db.flush()

    test_step = TestCaseStepModel(
        test_case_id=test_case.id,
        step_number=1,
        action="Execute the primary workflow described in the requirement.",
        expected_result="The system should behave as described in the requirement.",
    )
    db.add(test_step)

    requirement.status = "generated"
    await db.commit()
    await db.refresh(requirement)

    stmt = (
        select(Requirement)
        .where(Requirement.id == requirement_uuid)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
    )
    result = await db.execute(stmt)
    requirement = result.scalars().first()
    return requirement
