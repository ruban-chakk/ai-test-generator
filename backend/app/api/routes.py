import uuid
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import (
    ApprovalRecord,
    AuditLog,
    EvaluationRun,
    Feedback,
    GovernancePolicy,
    ImpactAnalysis,
    IntegrationRun,
    OperationalMetric,
    QualityEvaluation,
    Requirement,
    RepositorySyncRun,
    RevisionRecord,
    TestCase,
    TestCaseStep as TestCaseStepModel,
    TestCaseVersion,
    TestScenario,
)
from app.schemas import (
    ApprovalAction,
    ApprovalRecordSummary,
    AuditLogSummary,
    CleanupRequest,
    CleanupResult,
    EvaluationRunRequest,
    EvaluationRunSummary,
    FeedbackCreate,
    FeedbackRevisionRequest,
    FeedbackSummary,
    GovernancePolicyCreate,
    GovernancePolicySummary,
    ImpactAnalyzeRequest,
    ImpactAnalysisSummary,
    ImpactCandidate,
    IntegrationRunSummary,
    JiraImportRequest,
    MonitoringSummary,
    QualityEvaluationSummary,
    RepositorySyncRequest,
    RepositorySyncRunSummary,
    RequirementCreate,
    RequirementDetail,
    RevisionRecordSummary,
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
FEEDBACK_TYPES = {"revise", "generate_new", "deprecate", "accept", "reject"}
DUPLICATE_THRESHOLD = 0.80
UPDATE_THRESHOLD = 0.45
DEPRECATION_KEYWORDS = {
    "replace",
    "replaces",
    "replaced",
    "obsolete",
    "deprecated",
    "deprecate",
    "retire",
    "retired",
    "remove",
    "removed",
    "instead",
    "migrate",
    "migration",
}
ALLOWED_ROLES = {"reviewer", "approver", "admin", "system"}


def _actor(payload: ApprovalAction) -> str:
    return payload.approved_by or "system"


def _require_role(actor: str, allowed_roles: set[str] | None = None) -> None:
    role = actor.lower().strip() if actor else "system"
    allowed = allowed_roles or ALLOWED_ROLES
    if role not in allowed and role != "system":
        raise HTTPException(status_code=403, detail="Actor role is not allowed for this governance action")


def _clean_requirement_text(text: str) -> tuple[str, list[dict]]:
    original = text
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"(?i)\b(asap|tbd|todo|fixme)\b", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    issues: list[dict] = []
    if len(cleaned) < 20:
        issues.append({"field": "text", "severity": "error", "message": "Requirement text is too short after cleanup."})
    if original != cleaned:
        issues.append({"field": "text", "severity": "info", "message": "Whitespace and placeholder language were normalized."})
    if not re.search(r"\b(shall|should|must|can|when|then|verify|validate)\b", cleaned.lower()):
        issues.append({"field": "intent", "severity": "warning", "message": "Requirement intent is not explicit."})
    return cleaned, issues


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


def _quality_from_issues(issues: list[ValidationIssue]) -> tuple[int, str, list[dict]]:
    score = max(0, 100 - (len(issues) * 15))
    status = "passed" if score >= 85 else "needs_review" if score >= 60 else "failed"
    return score, status, [issue.dict() for issue in issues]


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2
        and token
        not in {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "should",
            "shall",
            "will",
            "from",
            "into",
            "case",
            "test",
            "requirement",
        }
    }


def _similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _case_text(test_case: TestCase) -> str:
    step_text = " ".join(
        f"{step.action} {step.expected_result}" for step in sorted(test_case.steps or [], key=lambda item: item.step_number)
    )
    return " ".join(
        value or ""
        for value in [
            test_case.title,
            test_case.description,
            test_case.prerequisite,
            test_case.priority,
            test_case.severity,
            test_case.category,
            test_case.type,
            step_text,
        ]
    )


def _candidate(
    test_case: TestCase,
    similarity: float,
    action: str,
    reason: str,
) -> ImpactCandidate:
    return ImpactCandidate(
        test_case_id=test_case.id,
        requirement_id=test_case.requirement_id,
        scenario_id=test_case.scenario_id,
        title=test_case.title,
        status=test_case.status,
        repository_status=test_case.repository_status,
        similarity=round(similarity, 3),
        recommended_action=action,
        reason=reason,
        priority=test_case.priority,
        severity=test_case.severity,
        category=test_case.category,
        type=test_case.type,
    )


async def _run_impact_analysis(
    db: AsyncSession,
    source_text: str,
    requirement_id: uuid.UUID | None,
    created_by: str = "system",
    context_ids: list[uuid.UUID] | None = None,
) -> ImpactAnalysisSummary:
    stmt = (
        select(TestCase)
        .where(TestCase.repository_status == "active")
        .options(selectinload(TestCase.steps))
        .order_by(TestCase.repository_synced_at.desc())
    )
    if context_ids:
        stmt = stmt.where(TestCase.requirement_id.in_(context_ids))

    result = await db.execute(stmt)
    approved_cases = result.scalars().all()
    duplicates: list[ImpactCandidate] = []
    deprecations: list[ImpactCandidate] = []
    updates: list[ImpactCandidate] = []
    source_tokens = _tokens(source_text)

    for test_case in approved_cases:
        score = _similarity(source_text, _case_text(test_case))
        case_tokens = _tokens(_case_text(test_case))
        keyword_overlap = source_tokens & DEPRECATION_KEYWORDS
        if score >= DUPLICATE_THRESHOLD:
            duplicates.append(
                _candidate(
                    test_case,
                    score,
                    "archive_duplicate",
                    "Similarity is at or above the 80% duplicate threshold.",
                )
            )
        elif keyword_overlap and score >= 0.25:
            deprecations.append(
                _candidate(
                    test_case,
                    score,
                    "mark_deprecated",
                    "Requirement language indicates replacement or retirement of overlapping approved coverage.",
                )
            )
        elif score >= UPDATE_THRESHOLD or (source_tokens & case_tokens and test_case.severity in {"major", "critical"}):
            updates.append(
                _candidate(
                    test_case,
                    score,
                    "review_update",
                    "Approved test case overlaps with the new requirement and should be reviewed for updates.",
                )
            )

    duplicates.sort(key=lambda item: item.similarity, reverse=True)
    deprecations.sort(key=lambda item: item.similarity, reverse=True)
    updates.sort(key=lambda item: item.similarity, reverse=True)

    coverage_score = min(100, (len(duplicates) * 35) + (len(updates) * 20) + (len(deprecations) * 10))
    risk_score = min(
        100,
        (len(deprecations) * 25)
        + (len(updates) * 15)
        + (20 if not duplicates and not updates else 0)
        + (10 if any(item.severity == "critical" for item in updates + deprecations) else 0),
    )
    summary = {
        "approved_cases_scanned": len(approved_cases),
        "duplicate_count": len(duplicates),
        "deprecation_count": len(deprecations),
        "update_count": len(updates),
        "manual_review_recommended": bool(deprecations or updates or risk_score >= 40),
        "thresholds": {"duplicate": DUPLICATE_THRESHOLD, "update": UPDATE_THRESHOLD},
    }

    analysis = ImpactAnalysis(
        requirement_id=requirement_id,
        source_text=source_text,
        similarity_threshold=int(DUPLICATE_THRESHOLD * 100),
        duplicates=jsonable_encoder(duplicates),
        deprecations=jsonable_encoder(deprecations),
        updates=jsonable_encoder(updates),
        risk_score=risk_score,
        coverage_score=coverage_score,
        summary=summary,
        created_by=created_by,
    )
    db.add(analysis)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="requirement" if requirement_id else "impact",
            entity_id=requirement_id,
            action="impact_analysis_completed",
            actor=created_by,
            details={"analysis_id": str(analysis.id), **summary},
        )
    )
    await db.commit()
    await db.refresh(analysis)

    return ImpactAnalysisSummary(
        id=analysis.id,
        requirement_id=requirement_id,
        source_text=source_text,
        similarity_threshold=DUPLICATE_THRESHOLD,
        duplicates=duplicates,
        deprecations=deprecations,
        updates=updates,
        risk_score=risk_score,
        coverage_score=coverage_score,
        summary=summary,
        created_by=created_by,
        created_at=analysis.created_at,
    )


def _test_case_snapshot(test_case: TestCase) -> dict:
    return {
        "id": str(test_case.id),
        "title": test_case.title,
        "description": test_case.description,
        "prerequisite": test_case.prerequisite,
        "priority": test_case.priority,
        "severity": test_case.severity,
        "category": test_case.category,
        "type": test_case.type,
        "status": test_case.status,
        "version": test_case.version,
        "steps": _step_snapshot(test_case),
    }


def _scenario_snapshot(scenario: TestScenario) -> dict:
    return {
        "id": str(scenario.id),
        "title": scenario.title,
        "description": scenario.description,
        "priority": scenario.priority,
        "severity": scenario.severity,
        "category": scenario.category,
        "type": scenario.type,
        "status": scenario.status,
        "version": scenario.version,
    }


async def _record_quality_evaluation(
    db: AsyncSession,
    target_level: str,
    target_id: uuid.UUID,
    issues: list[ValidationIssue],
    evaluated_by: str = "system",
) -> QualityEvaluation:
    score, status, issue_payload = _quality_from_issues(issues)
    evaluation = QualityEvaluation(
        target_level=target_level,
        target_id=target_id,
        score=score,
        status=status,
        metrics={
            "issue_count": len(issues),
            "guardrail_score": score,
        },
        issues=issue_payload,
        evaluated_by=evaluated_by,
    )
    db.add(evaluation)
    db.add(
        AuditLog(
            entity_type=target_level,
            entity_id=target_id,
            action="quality_evaluated",
            actor=evaluated_by,
            details={"score": score, "status": status, "issue_count": len(issues)},
        )
    )
    return evaluation


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
    if payload.feedback_type not in FEEDBACK_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported feedback type")
    if not payload.comment.strip():
        raise HTTPException(status_code=422, detail="Feedback comment is required")

    feedback = Feedback(
        target_level=payload.target_level,
        target_id=payload.target_id,
        source=payload.source,
        feedback_type=payload.feedback_type,
        comment=payload.comment,
        created_by=payload.created_by,
        vector_id=f"feedback:{payload.target_level}:{payload.target_id}:{uuid.uuid4()}",
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


@api_router.post(
    "/feedback/revise",
    response_model=RevisionRecordSummary,
    tags=["Feedback"],
)
async def process_feedback_revision(
    payload: FeedbackRevisionRequest,
    db: AsyncSession = Depends(get_db),
) -> RevisionRecordSummary:
    result = await db.execute(select(Feedback).where(Feedback.id == payload.feedback_id))
    feedback = result.scalars().first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    action = payload.action or feedback.feedback_type
    if action not in FEEDBACK_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported feedback action")

    source_snapshot: dict | None = None
    result_snapshot: dict | None = None

    if action == "generate_new":
        scenario: TestScenario | None = None
        if feedback.target_level == "scenario":
            result = await db.execute(select(TestScenario).where(TestScenario.id == feedback.target_id))
            scenario = result.scalars().first()
        elif feedback.target_level == "test_case":
            result = await db.execute(select(TestCase).where(TestCase.id == feedback.target_id))
            source_case = result.scalars().first()
            if source_case:
                result = await db.execute(select(TestScenario).where(TestScenario.id == source_case.scenario_id))
                scenario = result.scalars().first()
        else:
            result = await db.execute(
                select(TestScenario)
                .where(TestScenario.requirement_id == feedback.target_id)
                .order_by(TestScenario.created_at.asc())
            )
            scenario = result.scalars().first()

        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario context not found for new test case")

        source_snapshot = _scenario_snapshot(scenario)
        new_case = TestCase(
            scenario_id=scenario.id,
            requirement_id=scenario.requirement_id,
            title=f"Feedback-driven case: {scenario.title}",
            description=f"Generated from feedback: {feedback.comment}",
            prerequisite="Review the linked requirement and feedback context before execution.",
            priority=scenario.priority or "medium",
            severity=scenario.severity or "major",
            category=scenario.category or "functional",
            type=scenario.type or "regression",
            status="draft",
        )
        db.add(new_case)
        await db.flush()
        db.add(
            TestCaseStepModel(
                test_case_id=new_case.id,
                step_number=1,
                action="Execute the behavior requested by the feedback context.",
                expected_result="The system satisfies the feedback without regressing the original requirement.",
            )
        )
        result_snapshot = _test_case_snapshot(new_case)
    elif action == "revise":
        if feedback.target_level == "test_case":
            result = await db.execute(
                select(TestCase).where(TestCase.id == feedback.target_id).options(selectinload(TestCase.steps))
            )
            test_case = result.scalars().first()
            if not test_case:
                raise HTTPException(status_code=404, detail="Test case not found")
            source_snapshot = _test_case_snapshot(test_case)
            if test_case.locked:
                revised_case = TestCase(
                    scenario_id=test_case.scenario_id,
                    requirement_id=test_case.requirement_id,
                    title=f"{test_case.title} - revision",
                    description=f"{test_case.description}\n\nRevision context: {feedback.comment}",
                    prerequisite=test_case.prerequisite,
                    priority=test_case.priority,
                    severity=test_case.severity,
                    category=test_case.category,
                    type=test_case.type,
                    status="draft",
                    version=test_case.version + 1,
                )
                db.add(revised_case)
                await db.flush()
                for step in test_case.steps or []:
                    db.add(
                        TestCaseStepModel(
                            test_case_id=revised_case.id,
                            step_number=step.step_number,
                            action=step.action,
                            expected_result=step.expected_result,
                        )
                    )
                result_snapshot = _test_case_snapshot(revised_case)
            else:
                test_case.description = f"{test_case.description}\n\nRevision context: {feedback.comment}"
                test_case.status = "updated"
                test_case.version += 1
                result_snapshot = _test_case_snapshot(test_case)
        elif feedback.target_level == "scenario":
            result = await db.execute(select(TestScenario).where(TestScenario.id == feedback.target_id))
            scenario = result.scalars().first()
            if not scenario:
                raise HTTPException(status_code=404, detail="Scenario not found")
            source_snapshot = _scenario_snapshot(scenario)
            scenario.description = f"{scenario.description}\n\nRevision context: {feedback.comment}"
            scenario.status = "updated"
            scenario.version += 1
            result_snapshot = _scenario_snapshot(scenario)
        else:
            result = await db.execute(select(Requirement).where(Requirement.id == feedback.target_id))
            requirement = result.scalars().first()
            if not requirement:
                raise HTTPException(status_code=404, detail="Requirement not found")
            source_snapshot = {"id": str(requirement.id), "title": requirement.title, "description": requirement.description}
            requirement.status = "reviewed"
            requirement.metadata_json = {
                **(requirement.metadata_json or {}),
                "latest_feedback_context": feedback.comment,
            }
            result_snapshot = {
                "id": str(requirement.id),
                "status": requirement.status,
                "latest_feedback_context": feedback.comment,
            }
    elif action == "deprecate":
        if feedback.target_level == "test_case":
            result = await db.execute(
                select(TestCase).where(TestCase.id == feedback.target_id).options(selectinload(TestCase.steps))
            )
            test_case = result.scalars().first()
            if not test_case:
                raise HTTPException(status_code=404, detail="Test case not found")
            source_snapshot = _test_case_snapshot(test_case)
            test_case.status = "deprecated"
            test_case.repository_status = "deprecated"
            result_snapshot = _test_case_snapshot(test_case)
        elif feedback.target_level == "scenario":
            result = await db.execute(select(TestScenario).where(TestScenario.id == feedback.target_id))
            scenario = result.scalars().first()
            if not scenario:
                raise HTTPException(status_code=404, detail="Scenario not found")
            source_snapshot = _scenario_snapshot(scenario)
            scenario.status = "deprecated"
            result_snapshot = _scenario_snapshot(scenario)
        else:
            raise HTTPException(status_code=422, detail="Requirements cannot be deprecated through feedback")
    else:
        result_snapshot = {
            "feedback_id": str(feedback.id),
            "resolution": action,
            "comment": feedback.comment,
        }

    feedback.status = "resolved"
    feedback.resolved_at = datetime.utcnow()
    feedback.resolution_notes = payload.notes or f"Processed as {action}"

    revision = RevisionRecord(
        feedback_id=feedback.id,
        target_level=feedback.target_level,
        target_id=feedback.target_id,
        action=action,
        status="completed",
        created_by=payload.created_by,
        notes=payload.notes,
        source_snapshot=source_snapshot,
        result_snapshot=result_snapshot,
    )
    db.add(revision)
    await db.flush()
    db.add(
        AuditLog(
            entity_type=feedback.target_level,
            entity_id=feedback.target_id,
            action=f"feedback_{action}_processed",
            actor=payload.created_by,
            details={"feedback_id": str(feedback.id), "revision_id": str(revision.id)},
        )
    )
    await db.commit()
    await db.refresh(revision)
    return revision


@api_router.get(
    "/revisions",
    response_model=list[RevisionRecordSummary],
    tags=["Feedback"],
)
async def list_revisions(
    target_level: str | None = Query(None),
    target_id: uuid.UUID | None = Query(None),
    feedback_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[RevisionRecordSummary]:
    stmt = select(RevisionRecord)
    if target_level:
        stmt = stmt.where(RevisionRecord.target_level == target_level)
    if target_id:
        stmt = stmt.where(RevisionRecord.target_id == target_id)
    if feedback_id:
        stmt = stmt.where(RevisionRecord.feedback_id == feedback_id)
    stmt = stmt.order_by(RevisionRecord.created_at.desc())
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
    "/requirements/{requirement_id}/impact",
    response_model=ImpactAnalysisSummary,
    tags=["Impact"],
)
async def get_requirement_impact(
    requirement_id: str,
    db: AsyncSession = Depends(get_db),
) -> ImpactAnalysisSummary:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")

    result = await db.execute(select(Requirement).where(Requirement.id == requirement_uuid))
    requirement = result.scalars().first()
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    source_text = " ".join([requirement.title, requirement.description])
    return await _run_impact_analysis(db, source_text, requirement.id)


@api_router.post(
    "/impact/analyze",
    response_model=ImpactAnalysisSummary,
    tags=["Impact"],
)
async def analyze_impact(
    payload: ImpactAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
) -> ImpactAnalysisSummary:
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Impact analysis text is required")
    return await _run_impact_analysis(db, payload.text, None, payload.created_by, payload.context_ids)


@api_router.get(
    "/impact",
    response_model=list[ImpactAnalysisSummary],
    tags=["Impact"],
)
async def list_impact_analyses(
    requirement_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[ImpactAnalysisSummary]:
    stmt = select(ImpactAnalysis)
    if requirement_id:
        stmt = stmt.where(ImpactAnalysis.requirement_id == requirement_id)
    stmt = stmt.order_by(ImpactAnalysis.created_at.desc())
    result = await db.execute(stmt)
    analyses = result.scalars().all()
    return [
        ImpactAnalysisSummary(
            id=analysis.id,
            requirement_id=analysis.requirement_id,
            source_text=analysis.source_text,
            similarity_threshold=analysis.similarity_threshold / 100,
            duplicates=analysis.duplicates,
            deprecations=analysis.deprecations,
            updates=analysis.updates,
            risk_score=analysis.risk_score,
            coverage_score=analysis.coverage_score,
            summary=analysis.summary,
            created_by=analysis.created_by,
            created_at=analysis.created_at,
        )
        for analysis in analyses
    ]


@api_router.post(
    "/impact/test_cases/{test_case_id}/deprecate",
    response_model=TestCaseSummary,
    tags=["Impact"],
)
async def deprecate_impacted_test_case(
    test_case_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> TestCaseSummary:
    try:
        test_case_uuid = uuid.UUID(test_case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Test case not found")

    result = await db.execute(select(TestCase).where(TestCase.id == test_case_uuid).options(selectinload(TestCase.steps)))
    test_case = result.scalars().first()
    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")

    test_case.status = "deprecated"
    test_case.repository_status = "deprecated"
    actor = _actor(payload)
    db.add(
        AuditLog(
            entity_type="test_case",
            entity_id=test_case.id,
            action="impact_deprecated",
            actor=actor,
            details={"notes": payload.notes},
        )
    )
    await db.commit()
    await db.refresh(test_case)
    return test_case


@api_router.post(
    "/impact/test_cases/{test_case_id}/review-update",
    response_model=TestCaseSummary,
    tags=["Impact"],
)
async def flag_impacted_test_case_for_update(
    test_case_id: str,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> TestCaseSummary:
    try:
        test_case_uuid = uuid.UUID(test_case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Test case not found")

    result = await db.execute(select(TestCase).where(TestCase.id == test_case_uuid).options(selectinload(TestCase.steps)))
    test_case = result.scalars().first()
    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")

    test_case.status = "updated"
    test_case.repository_status = "needs_update"
    actor = _actor(payload)
    db.add(
        AuditLog(
            entity_type="test_case",
            entity_id=test_case.id,
            action="impact_update_review_flagged",
            actor=actor,
            details={"notes": payload.notes},
        )
    )
    await db.commit()
    await db.refresh(test_case)
    return test_case


@api_router.post(
    "/integrations/jira/import",
    response_model=IntegrationRunSummary,
    tags=["Integrations"],
)
async def import_jira_requirements(
    payload: JiraImportRequest,
    db: AsyncSession = Depends(get_db),
) -> IntegrationRunSummary:
    _require_role(payload.requested_by, {"admin", "system"})
    folder_path = payload.folder_path.strip()
    if not folder_path:
        raise HTTPException(status_code=422, detail="Jira folder path is required")

    raw_items = [item.strip() for item in re.split(r"[\n,]+", folder_path) if item.strip()]
    if not raw_items:
        raw_items = [folder_path]

    imported_ids: list[str] = []
    for item in raw_items:
        external_id = item if re.match(r"^[A-Z][A-Z0-9]+-\d+$", item) else f"JIRA-{len(imported_ids) + 1}"
        title = f"Imported Jira requirement {external_id}"
        description = f"Imported from Jira folder abstraction: {item}"
        cleaned_description, cleanup_issues = _clean_requirement_text(description)
        requirement = Requirement(
            external_id=external_id,
            title=title,
            description=cleaned_description,
            source="jira",
            status="draft",
            metadata_json={"import_source": item, "cleanup_issues": cleanup_issues},
            vector_id=f"requirement:{external_id}",
        )
        db.add(requirement)
        await db.flush()
        imported_ids.append(str(requirement.id))

    run = IntegrationRun(
        integration_type="jira_import",
        status="completed",
        requested_by=payload.requested_by,
        parameters={"folder_path": folder_path},
        result={"imported_count": len(imported_ids), "requirement_ids": imported_ids},
        completed_at=datetime.utcnow(),
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="integration",
            entity_id=run.id,
            action="jira_import_completed",
            actor=payload.requested_by,
            details=run.result,
        )
    )
    await db.commit()
    await db.refresh(run)
    return run


@api_router.post(
    "/integrations/test-repo/sync",
    response_model=RepositorySyncRunSummary,
    tags=["Integrations"],
)
async def sync_test_repository(
    payload: RepositorySyncRequest,
    db: AsyncSession = Depends(get_db),
) -> RepositorySyncRunSummary:
    _require_role(payload.requested_by, {"admin", "approver", "system"})
    result = await db.execute(
        select(TestCase)
        .where(TestCase.repository_status.in_(["active", "needs_update"]))
        .options(selectinload(TestCase.steps))
    )
    test_cases = result.scalars().all()
    synced_at = datetime.utcnow()
    vector_synced = 0

    for test_case in test_cases:
        test_case.repository_synced_at = synced_at
        test_case.repository_status = "active" if test_case.status == "approved" else test_case.repository_status
        if not test_case.vector_id:
            test_case.vector_id = f"test_case:{test_case.id}:v{test_case.version}"
        vector_synced += 1

    run = RepositorySyncRun(
        repository=payload.repository,
        branch=payload.branch,
        status="completed",
        synced_count=len(test_cases),
        vector_synced_count=vector_synced,
        requested_by=payload.requested_by,
        details={
            "mode": "metadata-and-vector-id-sync",
            "pinecone_index": "configured",
            "test_case_ids": [str(test_case.id) for test_case in test_cases],
        },
        completed_at=synced_at,
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="repository_sync",
            entity_id=run.id,
            action="test_repository_sync_completed",
            actor=payload.requested_by,
            details=run.details,
        )
    )
    await db.commit()
    await db.refresh(run)
    return run


@api_router.get(
    "/integrations/runs",
    response_model=list[IntegrationRunSummary],
    tags=["Integrations"],
)
async def list_integration_runs(
    integration_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationRunSummary]:
    stmt = select(IntegrationRun)
    if integration_type:
        stmt = stmt.where(IntegrationRun.integration_type == integration_type)
    stmt = stmt.order_by(IntegrationRun.started_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/integrations/test-repo/sync",
    response_model=list[RepositorySyncRunSummary],
    tags=["Integrations"],
)
async def list_repository_sync_runs(
    db: AsyncSession = Depends(get_db),
) -> list[RepositorySyncRunSummary]:
    result = await db.execute(select(RepositorySyncRun).order_by(RepositorySyncRun.started_at.desc()))
    return result.scalars().all()


@api_router.post(
    "/nlp/cleanup",
    response_model=CleanupResult,
    tags=["NLP"],
)
async def cleanup_requirement_text(payload: CleanupRequest) -> CleanupResult:
    cleaned_text, issues = _clean_requirement_text(payload.text)
    return CleanupResult(original_text=payload.text, cleaned_text=cleaned_text, issues=issues)


@api_router.post(
    "/evals/run",
    response_model=EvaluationRunSummary,
    tags=["Evaluation"],
)
async def run_quality_evaluation_suite(
    payload: EvaluationRunRequest,
    db: AsyncSession = Depends(get_db),
) -> EvaluationRunSummary:
    _require_role(payload.requested_by, {"admin", "approver", "system"})
    requirements_count = (await db.execute(select(func.count()).select_from(Requirement))).scalar_one()
    approved_cases_count = (
        await db.execute(select(func.count()).select_from(TestCase).where(TestCase.status == "approved"))
    ).scalar_one()
    open_feedback_count = (
        await db.execute(select(func.count()).select_from(Feedback).where(Feedback.status == "open"))
    ).scalar_one()
    failed_quality_count = (
        await db.execute(select(func.count()).select_from(QualityEvaluation).where(QualityEvaluation.status == "failed"))
    ).scalar_one()
    score = max(0, 100 - (open_feedback_count * 5) - (failed_quality_count * 15))
    issues = []
    if approved_cases_count == 0:
        issues.append({"severity": "warning", "message": "No approved test cases are available for repository sync."})
    if open_feedback_count:
        issues.append({"severity": "warning", "message": f"{open_feedback_count} feedback item(s) remain open."})
    status = "passed" if score >= 85 else "needs_review" if score >= 60 else "failed"
    run = EvaluationRun(
        suite=payload.suite,
        status=status,
        score=score,
        metrics={
            "requirements": requirements_count,
            "approved_test_cases": approved_cases_count,
            "open_feedback": open_feedback_count,
            "failed_quality_evaluations": failed_quality_count,
        },
        issues=issues,
        requested_by=payload.requested_by,
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="evaluation",
            entity_id=run.id,
            action="evaluation_suite_completed",
            actor=payload.requested_by,
            details={"suite": payload.suite, "score": score, "status": status},
        )
    )
    await db.commit()
    await db.refresh(run)
    return run


@api_router.get(
    "/evals",
    response_model=list[EvaluationRunSummary],
    tags=["Evaluation"],
)
async def list_evaluation_runs(
    db: AsyncSession = Depends(get_db),
) -> list[EvaluationRunSummary]:
    result = await db.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))
    return result.scalars().all()


@api_router.get(
    "/monitoring/summary",
    response_model=MonitoringSummary,
    tags=["Monitoring"],
)
async def monitoring_summary(
    db: AsyncSession = Depends(get_db),
) -> MonitoringSummary:
    metrics = {
        "requirements": (await db.execute(select(func.count()).select_from(Requirement))).scalar_one(),
        "approved_test_cases": (
            await db.execute(select(func.count()).select_from(TestCase).where(TestCase.status == "approved"))
        ).scalar_one(),
        "active_repository_cases": (
            await db.execute(select(func.count()).select_from(TestCase).where(TestCase.repository_status == "active"))
        ).scalar_one(),
        "open_feedback": (
            await db.execute(select(func.count()).select_from(Feedback).where(Feedback.status == "open"))
        ).scalar_one(),
        "impact_analyses": (await db.execute(select(func.count()).select_from(ImpactAnalysis))).scalar_one(),
        "integration_runs": (await db.execute(select(func.count()).select_from(IntegrationRun))).scalar_one(),
        "repository_sync_runs": (await db.execute(select(func.count()).select_from(RepositorySyncRun))).scalar_one(),
        "evaluation_runs": (await db.execute(select(func.count()).select_from(EvaluationRun))).scalar_one(),
    }
    for name, value in metrics.items():
        db.add(OperationalMetric(metric_name=name, metric_value=int(value), dimensions={"source": "summary"}))
    await db.commit()
    return MonitoringSummary(status="ok", metrics=metrics, captured_at=datetime.utcnow())


@api_router.post(
    "/governance/policies",
    response_model=GovernancePolicySummary,
    tags=["Governance"],
)
async def create_governance_policy(
    payload: GovernancePolicyCreate,
    db: AsyncSession = Depends(get_db),
) -> GovernancePolicySummary:
    _require_role(payload.created_by, {"admin", "system"})
    result = await db.execute(select(GovernancePolicy).where(GovernancePolicy.name == payload.name))
    policy = result.scalars().first()
    if policy:
        policy.status = payload.status
        policy.policy_type = payload.policy_type
        policy.rules = payload.rules
    else:
        policy = GovernancePolicy(
            name=payload.name,
            status=payload.status,
            policy_type=payload.policy_type,
            rules=payload.rules,
            created_by=payload.created_by,
        )
        db.add(policy)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="governance_policy",
            entity_id=policy.id,
            action="governance_policy_created",
            actor=payload.created_by,
            details={"name": payload.name, "policy_type": payload.policy_type},
        )
    )
    await db.commit()
    await db.refresh(policy)
    return policy


@api_router.get(
    "/governance/policies",
    response_model=list[GovernancePolicySummary],
    tags=["Governance"],
)
async def list_governance_policies(
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[GovernancePolicySummary]:
    stmt = select(GovernancePolicy)
    if status:
        stmt = stmt.where(GovernancePolicy.status == status)
    stmt = stmt.order_by(GovernancePolicy.updated_at.desc())
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


async def _collect_validation_issues(
    db: AsyncSession,
    target_level: str,
    target_uuid: uuid.UUID,
) -> list[ValidationIssue]:
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
    return issues


@api_router.post(
    "/quality/{target_level}/{target_id}",
    response_model=QualityEvaluationSummary,
    tags=["Quality"],
)
async def evaluate_quality(
    target_level: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
) -> QualityEvaluationSummary:
    if target_level not in TARGET_LEVELS:
        raise HTTPException(status_code=422, detail="Target level must be requirement, scenario, or test_case")
    try:
        target_uuid = uuid.UUID(target_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Target not found")

    issues = await _collect_validation_issues(db, target_level, target_uuid)
    evaluation = await _record_quality_evaluation(db, target_level, target_uuid, issues)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@api_router.get(
    "/quality",
    response_model=list[QualityEvaluationSummary],
    tags=["Quality"],
)
async def list_quality_evaluations(
    target_level: str | None = Query(None),
    target_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[QualityEvaluationSummary]:
    stmt = select(QualityEvaluation)
    if target_level:
        stmt = stmt.where(QualityEvaluation.target_level == target_level)
    if target_id:
        stmt = stmt.where(QualityEvaluation.target_id == target_id)
    stmt = stmt.order_by(QualityEvaluation.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


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
