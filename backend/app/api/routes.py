import uuid
import re
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.core.config import settings
from app.core.security import current_principal, require_global_role
from app.models import (
    ApprovalRecord,
    AuditLog,
    EvaluationRun,
    Feedback,
    GovernancePolicy,
    ImpactAnalysis,
    IntegrationRun,
    OperationalMetric,
    OutboxEvent,
    Project,
    ProjectMembership,
    QualityEvaluation,
    Requirement,
    RepositorySyncRun,
    RevisionRecord,
    TestCase,
    TestCaseStep as TestCaseStepModel,
    TestCaseVersion,
    TestExecutionRun,
    TestScenario,
    User,
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
    DependencyHealthSummary,
    DependencyStatusSummary,
    OutboxEventSummary,
    ProjectCreate,
    ProjectMembershipSummary,
    ProjectMembershipUpsert,
    ProjectSummary,
    QualityEvaluationSummary,
    RepositorySyncRequest,
    RepositorySyncRunSummary,
    SemanticSearchResult,
    RequirementCreate,
    RequirementDetail,
    RevisionRecordSummary,
    TestCaseCreate,
    TestCaseStep,
    TestCaseStepCreate,
    TestCaseSummary,
    TestCaseVersionSummary,
    TestExecutionRequest,
    TestExecutionRunSummary,
    TestScenarioCreate,
    TestScenarioSummary,
    ValidationIssue,
    ValidationResult,
)
from app.services.generation import (
    GenerationConfigurationError,
    GenerationProviderError,
    build_generation_service,
)
from app.services.outbox import (
    FEEDBACK_INDEX_REQUESTED,
    REQUIREMENT_INDEX_REQUESTED,
    TEST_CASE_INDEX_REQUESTED,
    TEST_CASE_REPOSITORY_SYNC_REQUESTED,
    TEST_CASE_EXECUTION_REQUESTED,
    enqueue_outbox_event,
    enqueue_index_event,
)
from app.services.impact import build_semantic_impact_service
from app.services.integrations import (
    IntegrationConfigurationError,
    IntegrationProviderError,
    JiraCloudClient,
)
from app.services.file_ingestion import FileIngestionError, parse_requirement_file
from app.services.health import probe_external_dependencies
from app.services.search import build_semantic_search_service

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


async def _require_project_access(
    db: AsyncSession,
    project_id: uuid.UUID | None,
    allowed_roles: set[str] | None = None,
) -> None:
    principal = current_principal()
    if principal.role == "admin":
        return
    if project_id is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    result = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user_id,
        )
    )
    membership = result.scalars().first()
    if not membership:
        raise HTTPException(status_code=404, detail="Resource not found")
    if allowed_roles and membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient project role for this action")


async def _require_requirement_access(
    db: AsyncSession,
    requirement_id: uuid.UUID,
    allowed_roles: set[str] | None = None,
) -> None:
    result = await db.execute(select(Requirement.project_id).where(Requirement.id == requirement_id))
    project_id = result.scalar_one_or_none()
    if project_id is None:
        principal = current_principal()
        exists = await db.execute(select(Requirement.id).where(Requirement.id == requirement_id))
        if principal.role != "admin" or exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Requirement not found")
        return
    await _require_project_access(db, project_id, allowed_roles)


async def _require_target_access(
    db: AsyncSession,
    target_level: str,
    target_id: uuid.UUID,
    allowed_roles: set[str] | None = None,
) -> None:
    if target_level == "requirement":
        requirement_id = target_id
    elif target_level == "scenario":
        result = await db.execute(
            select(TestScenario.requirement_id).where(TestScenario.id == target_id)
        )
        requirement_id = result.scalar_one_or_none()
    elif target_level == "test_case":
        result = await db.execute(select(TestCase.requirement_id).where(TestCase.id == target_id))
        requirement_id = result.scalar_one_or_none()
    else:
        raise HTTPException(status_code=422, detail="Unsupported target level")
    if requirement_id is None:
        raise HTTPException(status_code=404, detail="Target not found")
    await _require_requirement_access(db, requirement_id, allowed_roles)


async def _ensure_project(db: AsyncSession, project_id: uuid.UUID | None) -> Project | None:
    principal = current_principal()
    if project_id is None:
        if principal.role != "admin":
            raise HTTPException(status_code=422, detail="A project is required")
        return None

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if principal.role != "admin":
        await _require_project_access(db, project_id)
    return project


def _actor(payload: ApprovalAction) -> str:
    return current_principal().username


def _require_role(actor: str, allowed_roles: set[str] | None = None) -> None:
    allowed = allowed_roles or ALLOWED_ROLES
    require_global_role(*sorted(role for role in allowed if role != "system"))


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
    return score, status, [issue.model_dump() for issue in issues]


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


def _semantic_candidate(
    metadata: dict,
    similarity: float,
    action: str,
    reason: str,
) -> ImpactCandidate:
    return ImpactCandidate(
        test_case_id=uuid.UUID(metadata["entity_id"]),
        requirement_id=uuid.UUID(metadata["requirement_id"]),
        scenario_id=uuid.UUID(metadata["scenario_id"]),
        title=metadata.get("title") or "Indexed test case",
        status=metadata.get("status") or "approved",
        repository_status="indexed",
        similarity=round(similarity, 3),
        recommended_action=action,
        reason=reason,
        priority=metadata.get("priority") or None,
        severity=metadata.get("severity") or None,
        category=metadata.get("category") or None,
        type=metadata.get("type") or None,
    )


async def _run_impact_analysis(
    db: AsyncSession,
    source_text: str,
    requirement_id: uuid.UUID | None,
    project_id: uuid.UUID,
    created_by: str = "system",
    context_ids: list[uuid.UUID] | None = None,
) -> ImpactAnalysisSummary:
    try:
        semantic_service = build_semantic_impact_service()
        matches = await semantic_service.search(source_text, project_id=str(project_id))
    except GenerationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    allowed_requirement_ids = {str(item) for item in context_ids or []}
    if allowed_requirement_ids:
        matches = [
            match
            for match in matches
            if str(match.metadata.get("requirement_id")) in allowed_requirement_ids
        ]
    duplicates: list[ImpactCandidate] = []
    deprecations: list[ImpactCandidate] = []
    updates: list[ImpactCandidate] = []
    source_tokens = _tokens(source_text)

    for match in matches:
        score = match.score
        keyword_overlap = source_tokens & DEPRECATION_KEYWORDS
        try:
            if score >= DUPLICATE_THRESHOLD:
                duplicates.append(
                    _semantic_candidate(
                        match.metadata,
                        score,
                        "archive_duplicate",
                        "Semantic similarity is at or above the 80% duplicate threshold.",
                    )
                )
            elif keyword_overlap and score >= 0.25:
                deprecations.append(
                    _semantic_candidate(
                        match.metadata,
                        score,
                        "mark_deprecated",
                        "Requirement language indicates replacement or retirement of semantically overlapping coverage.",
                    )
                )
            elif score >= UPDATE_THRESHOLD:
                updates.append(
                    _semantic_candidate(
                        match.metadata,
                        score,
                        "review_update",
                        "Approved test case semantically overlaps with the new requirement and should be reviewed.",
                    )
                )
        except (KeyError, TypeError, ValueError):
            continue

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
        "approved_cases_scanned": len(matches),
        "duplicate_count": len(duplicates),
        "deprecation_count": len(deprecations),
        "update_count": len(updates),
        "manual_review_recommended": bool(deprecations or updates or risk_score >= 40),
        "thresholds": {"duplicate": DUPLICATE_THRESHOLD, "update": UPDATE_THRESHOLD},
        "similarity_mode": "embedding_cosine",
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


async def _create_generated_test_case(
    db: AsyncSession,
    *,
    requirement_id: uuid.UUID,
    scenario_id: uuid.UUID,
    generated_case,
    version: int = 1,
) -> tuple[TestCase, dict]:
    test_case = TestCase(
        scenario_id=scenario_id,
        requirement_id=requirement_id,
        title=generated_case.title,
        description=generated_case.description,
        prerequisite=generated_case.prerequisite,
        priority=generated_case.priority,
        severity=generated_case.severity,
        category=generated_case.category,
        type=generated_case.type,
        status="draft",
        version=version,
    )
    db.add(test_case)
    await db.flush()
    for generated_step in generated_case.steps:
        db.add(
            TestCaseStepModel(
                test_case_id=test_case.id,
                step_number=generated_step.step_number,
                action=generated_step.action,
                expected_result=generated_step.expected_result,
            )
        )
    snapshot = {
        "id": str(test_case.id),
        **generated_case.model_dump(),
        "status": "draft",
        "version": version,
    }
    return test_case, snapshot


async def _create_generated_scenario(db: AsyncSession, requirement_id: uuid.UUID, generated_scenario) -> dict:
    scenario = TestScenario(
        requirement_id=requirement_id,
        title=generated_scenario.title,
        description=generated_scenario.description,
        priority=generated_scenario.priority,
        severity=generated_scenario.severity,
        category=generated_scenario.category,
        type=generated_scenario.type,
        status="draft",
    )
    db.add(scenario)
    await db.flush()
    case_snapshots = []
    for generated_case in generated_scenario.test_cases:
        _, case_snapshot = await _create_generated_test_case(
            db,
            requirement_id=requirement_id,
            scenario_id=scenario.id,
            generated_case=generated_case,
        )
        case_snapshots.append(case_snapshot)
    return {**_scenario_snapshot(scenario), "test_cases": case_snapshots}


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
    "/projects",
    response_model=list[ProjectSummary],
    tags=["Projects"],
)
async def list_projects(
    db: AsyncSession = Depends(get_db),
) -> list[ProjectSummary]:
    principal = current_principal()
    requirement_counts = (
        select(Requirement.project_id, func.count(Requirement.id).label("requirement_count"))
        .group_by(Requirement.project_id)
        .subquery()
    )
    test_case_counts = (
        select(Requirement.project_id, func.count(TestCase.id).label("test_case_count"))
        .join(TestCase, TestCase.requirement_id == Requirement.id)
        .group_by(Requirement.project_id)
        .subquery()
    )
    stmt = (
        select(
            Project,
            func.coalesce(requirement_counts.c.requirement_count, 0),
            func.coalesce(test_case_counts.c.test_case_count, 0),
        )
        .outerjoin(requirement_counts, requirement_counts.c.project_id == Project.id)
        .outerjoin(test_case_counts, test_case_counts.c.project_id == Project.id)
        .order_by(Project.name.asc())
    )
    if principal.role != "admin":
        stmt = stmt.join(
            ProjectMembership,
            ProjectMembership.project_id == Project.id,
        ).where(ProjectMembership.user_id == principal.user_id)
    result = await db.execute(stmt)
    projects: list[ProjectSummary] = []
    for project, requirement_count, test_case_count in result.all():
        projects.append(
            ProjectSummary(
                id=project.id,
                name=project.name,
                description=project.description,
                status=project.status,
                requirement_count=requirement_count,
                test_case_count=test_case_count,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )
    return projects


@api_router.post(
    "/projects",
    response_model=ProjectSummary,
    tags=["Projects"],
)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ProjectSummary:
    principal = require_global_role("admin")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name is required")

    existing = await db.execute(select(Project).where(func.lower(Project.name) == name.lower()))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Project name already exists")

    project = Project(
        name=name,
        description=payload.description.strip() if payload.description else None,
        status=payload.status or "active",
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMembership(
            project_id=project.id,
            user_id=principal.user_id,
            role="admin",
        )
    )
    await db.commit()
    await db.refresh(project)
    return ProjectSummary(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        requirement_count=0,
        test_case_count=0,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@api_router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMembershipSummary],
    tags=["Projects"],
)
async def list_project_members(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ProjectMembershipSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"admin"})
    result = await db.execute(
        select(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .where(ProjectMembership.project_id == project_id)
        .order_by(User.username.asc())
    )
    return [
        ProjectMembershipSummary(
            id=membership.id,
            project_id=membership.project_id,
            user_id=user.id,
            username=user.username,
            email=user.email,
            role=membership.role,
            created_at=membership.created_at,
        )
        for membership, user in result.all()
    ]


@api_router.put(
    "/projects/{project_id}/members",
    response_model=ProjectMembershipSummary,
    tags=["Projects"],
)
async def upsert_project_member(
    project_id: uuid.UUID,
    payload: ProjectMembershipUpsert,
    db: AsyncSession = Depends(get_db),
) -> ProjectMembershipSummary:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"admin"})
    if payload.role not in {"reviewer", "approver", "admin"}:
        raise HTTPException(status_code=422, detail="Unsupported project role")
    user = await db.get(User, payload.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=404, detail="User not found")
    result = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == payload.user_id,
        )
    )
    membership = result.scalars().first()
    action = "project_member_role_updated"
    if membership:
        membership.role = payload.role
    else:
        action = "project_member_added"
        membership = ProjectMembership(
            project_id=project_id,
            user_id=payload.user_id,
            role=payload.role,
        )
        db.add(membership)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="project",
            entity_id=project_id,
            action=action,
            actor=current_principal().username,
            details={"user_id": str(user.id), "role": payload.role},
        )
    )
    await db.commit()
    await db.refresh(membership)
    return ProjectMembershipSummary(
        id=membership.id,
        project_id=membership.project_id,
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=membership.role,
        created_at=membership.created_at,
    )


@api_router.get(
    "/requirements",
    response_model=list[RequirementDetail],
    tags=["Requirements"],
)
async def list_requirements(
    project_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    source: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[RequirementDetail]:
    principal = current_principal()
    stmt = (
        select(Requirement)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
        .order_by(Requirement.updated_at.desc())
    )

    if project_id:
        await _ensure_project(db, project_id)
        stmt = stmt.where(Requirement.project_id == project_id)

    if principal.role != "admin":
        stmt = stmt.join(
            ProjectMembership,
            ProjectMembership.project_id == Requirement.project_id,
        ).where(ProjectMembership.user_id == principal.user_id)

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

    result = await db.execute(stmt.limit(limit).offset(offset))
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
    await _ensure_project(db, payload.project_id)
    requirement = Requirement(
        project_id=payload.project_id,
        external_id=payload.external_id,
        title=payload.title,
        description=payload.description,
        source=payload.source,
        status="draft",
    )
    db.add(requirement)
    await db.flush()
    enqueue_index_event(
        db,
        event_key=f"requirement.index:{requirement.id}:created",
        event_type=REQUIREMENT_INDEX_REQUESTED,
        aggregate_type="requirement",
        aggregate_id=requirement.id,
    )
    await db.commit()
    stmt = (
        select(Requirement)
        .where(Requirement.id == requirement.id)
        .options(
            selectinload(Requirement.scenarios)
            .selectinload(TestScenario.test_cases)
            .selectinload(TestCase.steps)
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one()


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

    await _require_requirement_access(db, requirement_uuid)

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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, requirement_uuid, {"approver", "admin"})

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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, requirement_uuid, {"approver", "admin"})

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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, scenario.requirement_id, {"approver", "admin"})

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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, scenario.requirement_id, {"approver", "admin"})

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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, test_case.requirement_id, {"approver", "admin"})

    issues = _validate_test_case_content(test_case)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={"message": "Test case failed governance validation", "issues": [issue.model_dump() for issue in issues]},
        )

    if test_case.status == "approved":
        test_case.version += 1
    test_case.status = "approved"
    test_case.approved_at = datetime.utcnow()
    test_case.locked = True
    test_case.repository_status = "pending_index"
    test_case.repository_synced_at = None
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
    enqueue_index_event(
        db,
        event_key=f"test_case.index:{test_case.id}:v{test_case.version}",
        event_type=TEST_CASE_INDEX_REQUESTED,
        aggregate_type="test_case",
        aggregate_id=test_case.id,
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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, test_case.requirement_id, {"approver", "admin"})

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
    await _require_target_access(db, payload.target_level, payload.target_id)
    actor = current_principal().username

    feedback = Feedback(
        target_level=payload.target_level,
        target_id=payload.target_id,
        source=payload.source,
        feedback_type=payload.feedback_type,
        comment=payload.comment,
        created_by=actor,
    )
    db.add(feedback)
    await db.flush()
    feedback.vector_id = f"feedback:{feedback.id}"
    enqueue_index_event(
        db,
        event_key=f"feedback.index:{feedback.id}",
        event_type=FEEDBACK_INDEX_REQUESTED,
        aggregate_type="feedback",
        aggregate_id=feedback.id,
    )
    audit = AuditLog(
        entity_type="feedback",
        entity_id=feedback.id,
        action="feedback_created",
        actor=actor,
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
    if target_level and target_id:
        await _require_target_access(db, target_level, target_id)
    elif current_principal().role != "admin":
        raise HTTPException(status_code=422, detail="target_level and target_id are required")
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
    await _require_target_access(db, feedback.target_level, feedback.target_id)
    actor = current_principal().username

    action = payload.action or feedback.feedback_type
    if action not in FEEDBACK_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported feedback action")
    if feedback.status == "resolved":
        previous = await db.execute(
            select(RevisionRecord)
            .where(RevisionRecord.feedback_id == feedback.id)
            .order_by(RevisionRecord.created_at.desc())
        )
        previous_revision = previous.scalars().first()
        if previous_revision:
            return previous_revision
        raise HTTPException(status_code=409, detail="Feedback has already been resolved")
    if action == "deprecate":
        require_global_role("approver", "admin")
        await _require_target_access(db, feedback.target_level, feedback.target_id, {"approver", "admin"})

    source_snapshot: dict | None = None
    result_snapshot: dict | None = None

    if action in {"generate_new", "revise"}:
        scenario: TestScenario | None = None
        source_case: TestCase | None = None
        if feedback.target_level == "test_case":
            result = await db.execute(
                select(TestCase).where(TestCase.id == feedback.target_id).options(selectinload(TestCase.steps))
            )
            source_case = result.scalars().first()
            if not source_case:
                raise HTTPException(status_code=404, detail="Test case not found")
            scenario = await db.get(TestScenario, source_case.scenario_id)
            requirement_id = source_case.requirement_id
            source_snapshot = _test_case_snapshot(source_case)
            target_context = jsonable_encoder(source_snapshot)
        elif feedback.target_level == "scenario":
            scenario = await db.get(TestScenario, feedback.target_id)
            if not scenario:
                raise HTTPException(status_code=404, detail="Scenario not found")
            requirement_id = scenario.requirement_id
            source_snapshot = _scenario_snapshot(scenario)
            target_context = jsonable_encoder(source_snapshot)
        else:
            requirement_id = feedback.target_id
            target_context = {"target_level": "requirement", "target_id": str(feedback.target_id)}

        requirement = await db.get(Requirement, requirement_id)
        if not requirement:
            raise HTTPException(status_code=404, detail="Requirement not found")
        if source_snapshot is None:
            source_snapshot = {
                "id": str(requirement.id),
                "title": requirement.title,
                "description": requirement.description,
            }
            target_context = source_snapshot

        try:
            generation_result = await build_generation_service().generate_from_feedback(
                requirement_id=str(requirement.id),
                project_id=str(requirement.project_id) if requirement.project_id else None,
                title=requirement.title,
                description=requirement.description,
                external_id=requirement.external_id,
                feedback_text=feedback.comment,
                target_context=str(target_context),
                action=action,
            )
        except GenerationConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except GenerationProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        generated_scenario = generation_result.draft.scenarios[0]
        if action == "generate_new" and scenario is not None:
            _, result_snapshot = await _create_generated_test_case(
                db,
                requirement_id=requirement.id,
                scenario_id=scenario.id,
                generated_case=generated_scenario.test_cases[0],
            )
        elif action == "revise" and source_case is not None:
            generated_case = generated_scenario.test_cases[0]
            if source_case.locked:
                _, result_snapshot = await _create_generated_test_case(
                    db,
                    requirement_id=requirement.id,
                    scenario_id=source_case.scenario_id,
                    generated_case=generated_case,
                    version=source_case.version + 1,
                )
            else:
                source_case.title = generated_case.title
                source_case.description = generated_case.description
                source_case.prerequisite = generated_case.prerequisite
                source_case.priority = generated_case.priority
                source_case.severity = generated_case.severity
                source_case.category = generated_case.category
                source_case.type = generated_case.type
                source_case.status = "updated"
                source_case.version += 1
                await db.execute(delete(TestCaseStepModel).where(TestCaseStepModel.test_case_id == source_case.id))
                for generated_step in generated_case.steps:
                    db.add(
                        TestCaseStepModel(
                            test_case_id=source_case.id,
                            step_number=generated_step.step_number,
                            action=generated_step.action,
                            expected_result=generated_step.expected_result,
                        )
                    )
                result_snapshot = {
                    "id": str(source_case.id),
                    **generated_case.model_dump(),
                    "status": source_case.status,
                    "version": source_case.version,
                }
        elif action == "revise" and scenario is not None:
            scenario.title = generated_scenario.title
            scenario.description = generated_scenario.description
            scenario.priority = generated_scenario.priority
            scenario.severity = generated_scenario.severity
            scenario.category = generated_scenario.category
            scenario.type = generated_scenario.type
            scenario.status = "updated"
            scenario.version += 1
            result_snapshot = _scenario_snapshot(scenario)
        else:
            generated_snapshots = []
            for item in generation_result.draft.scenarios:
                generated_snapshots.append(await _create_generated_scenario(db, requirement.id, item))
            requirement.status = "generated"
            result_snapshot = {
                "requirement_id": str(requirement.id),
                "generated_scenarios": generated_snapshots,
            }

        result_snapshot = {
            **(result_snapshot or {}),
            "generation": {
                "model": generation_result.model,
                "retrieved_vector_ids": [item.id for item in generation_result.retrieved_context],
            },
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
        created_by=actor,
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
            actor=actor,
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
    if target_level and target_id:
        await _require_target_access(db, target_level, target_id)
    elif current_principal().role != "admin":
        raise HTTPException(status_code=422, detail="target_level and target_id are required")
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
    if target_level and target_id:
        await _require_target_access(db, target_level, target_id)
    elif current_principal().role != "admin":
        raise HTTPException(status_code=422, detail="target_level and target_id are required")
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
    if entity_type in TARGET_LEVELS and entity_id:
        await _require_target_access(db, entity_type, entity_id)
    elif current_principal().role != "admin":
        raise HTTPException(status_code=422, detail="A requirement, scenario, or test_case target is required")
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

    await _require_target_access(db, "test_case", test_case_uuid)

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
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[TestCaseSummary]:
    principal = current_principal()
    stmt = select(TestCase).options(selectinload(TestCase.steps)).order_by(TestCase.repository_synced_at.desc())
    if principal.role != "admin":
        stmt = (
            stmt.join(Requirement, Requirement.id == TestCase.requirement_id)
            .join(ProjectMembership, ProjectMembership.project_id == Requirement.project_id)
            .where(ProjectMembership.user_id == principal.user_id)
        )
    if status:
        stmt = stmt.where(TestCase.repository_status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.get(
    "/search",
    response_model=list[SemanticSearchResult],
    tags=["Search"],
)
async def semantic_search(
    project_id: uuid.UUID,
    query: str = Query(..., min_length=2, max_length=500),
    entity_type: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[SemanticSearchResult]:
    await _ensure_project(db, project_id)
    if entity_type and entity_type not in {"requirement", "test_case", "feedback"}:
        raise HTTPException(status_code=422, detail="Unsupported semantic search entity type")
    try:
        matches = await build_semantic_search_service().search(
            query.strip(),
            project_id=str(project_id),
            entity_type=entity_type,
            limit=limit,
        )
    except GenerationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        SemanticSearchResult(
            vector_id=match.vector_id,
            entity_type=match.entity_type,
            entity_id=match.entity_id,
            title=match.title,
            text=match.text,
            score=round(match.score, 4),
            metadata=match.metadata,
        )
        for match in matches
    ]


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

    await _require_requirement_access(db, requirement_uuid)

    result = await db.execute(select(Requirement).where(Requirement.id == requirement_uuid))
    requirement = result.scalars().first()
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    if not requirement.project_id:
        raise HTTPException(status_code=422, detail="Requirement must belong to a project for semantic impact analysis")

    source_text = " ".join([requirement.title, requirement.description])
    return await _run_impact_analysis(
        db,
        source_text,
        requirement.id,
        requirement.project_id,
        current_principal().username,
    )


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
    principal = current_principal()
    if not payload.project_id:
        raise HTTPException(status_code=422, detail="project_id is required for semantic impact analysis")
    await _ensure_project(db, payload.project_id)
    for requirement_id in payload.context_ids or []:
        await _require_requirement_access(db, requirement_id)
        context_project = await db.scalar(
            select(Requirement.project_id).where(Requirement.id == requirement_id)
        )
        if context_project != payload.project_id:
            raise HTTPException(status_code=422, detail="All context requirements must belong to the selected project")
    return await _run_impact_analysis(
        db,
        payload.text,
        None,
        payload.project_id,
        principal.username,
        payload.context_ids,
    )


@api_router.get(
    "/impact",
    response_model=list[ImpactAnalysisSummary],
    tags=["Impact"],
)
async def list_impact_analyses(
    requirement_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[ImpactAnalysisSummary]:
    if requirement_id:
        await _require_requirement_access(db, requirement_id)
    elif current_principal().role != "admin":
        raise HTTPException(status_code=422, detail="requirement_id is required")
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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, test_case.requirement_id, {"approver", "admin"})

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

    require_global_role("approver", "admin")
    await _require_requirement_access(db, test_case.requirement_id, {"approver", "admin"})

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
    "/requirements/import-file",
    response_model=IntegrationRunSummary,
    tags=["Requirements"],
)
async def import_requirement_file(
    project_id: uuid.UUID = Form(...),
    uploaded_file: UploadFile = File(..., alias="file"),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRunSummary:
    await _ensure_project(db, project_id)
    allowed_content_types = {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/csv",
        "application/json",
        "application/octet-stream",
    }
    if uploaded_file.content_type and uploaded_file.content_type.lower() not in allowed_content_types:
        raise HTTPException(status_code=415, detail="Unsupported requirement file content type")
    content = await uploaded_file.read(settings.upload_max_bytes + 1)
    filename = uploaded_file.filename
    await uploaded_file.close()
    try:
        parsed = parse_requirement_file(
            filename,
            content,
            max_bytes=settings.upload_max_bytes,
            max_requirements=settings.upload_max_requirements,
        )
    except FileIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    actor = current_principal().username
    created_count = 0
    existing_count = 0
    requirement_ids: list[str] = []
    for item in parsed:
        result = await db.execute(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.external_id == item.external_id,
            )
        )
        requirement = result.scalars().first()
        if requirement:
            existing_count += 1
        else:
            cleaned_description, cleanup_issues = _clean_requirement_text(item.description)
            requirement = Requirement(
                project_id=project_id,
                external_id=item.external_id,
                title=item.title,
                description=cleaned_description,
                source="upload",
                status="draft",
                metadata_json={**item.metadata, "cleanup_issues": cleanup_issues},
            )
            db.add(requirement)
            await db.flush()
            enqueue_index_event(
                db,
                event_key=f"requirement.index:{requirement.id}:file-import",
                event_type=REQUIREMENT_INDEX_REQUESTED,
                aggregate_type="requirement",
                aggregate_id=requirement.id,
            )
            created_count += 1
        requirement_ids.append(str(requirement.id))

    first_metadata = parsed[0].metadata
    run = IntegrationRun(
        integration_type="file_import",
        status="completed",
        requested_by=actor,
        parameters={
            "project_id": str(project_id),
            "filename": first_metadata["upload_filename"],
            "sha256": first_metadata["upload_sha256"],
            "bytes": len(content),
        },
        result={
            "parsed_count": len(parsed),
            "created_count": created_count,
            "existing_count": existing_count,
            "requirement_ids": requirement_ids,
        },
        completed_at=datetime.utcnow(),
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="integration",
            entity_id=run.id,
            action="requirement_file_imported",
            actor=actor,
            details={
                "project_id": str(project_id),
                "sha256": first_metadata["upload_sha256"],
                "created_count": created_count,
                "existing_count": existing_count,
            },
        )
    )
    await db.commit()
    await db.refresh(run)
    return run


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
    actor = current_principal().username
    await _ensure_project(db, payload.project_id)
    jql = payload.jql.strip()
    if not jql:
        raise HTTPException(status_code=422, detail="JQL is required")
    run = IntegrationRun(
        integration_type="jira_import",
        status="running",
        requested_by=actor,
        parameters={
            "project_id": str(payload.project_id),
            "jql": jql,
            "max_results": payload.max_results,
        },
        result={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    try:
        issues = await JiraCloudClient().search_issues(jql, payload.max_results)
    except IntegrationConfigurationError as exc:
        run.status = "failed"
        run.result = {"error_type": "configuration"}
        run.completed_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntegrationProviderError as exc:
        run.status = "failed"
        run.result = {"error_type": "provider"}
        run.completed_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    imported_ids: list[str] = []
    created_count = 0
    updated_count = 0
    for issue in issues:
        existing = await db.execute(
            select(Requirement).where(
                Requirement.project_id == payload.project_id,
                Requirement.external_id == issue.key,
            )
        )
        requirement = existing.scalars().first()
        cleaned_description, cleanup_issues = _clean_requirement_text(issue.description or issue.summary)
        metadata = {
            "jira_issue_type": issue.issue_type,
            "jira_status": issue.status,
            "jira_updated": issue.updated,
            "cleanup_issues": cleanup_issues,
        }
        if requirement:
            requirement.title = issue.summary
            requirement.description = cleaned_description
            requirement.metadata_json = metadata
            requirement.status = "draft"
            updated_count += 1
        else:
            requirement = Requirement(
                project_id=payload.project_id,
                external_id=issue.key,
                title=issue.summary,
                description=cleaned_description,
                source="jira",
                status="draft",
                metadata_json=metadata,
            )
            db.add(requirement)
            await db.flush()
            created_count += 1
        digest = hashlib.sha256(
            f"{issue.updated or ''}\n{issue.summary}\n{cleaned_description}".encode("utf-8")
        ).hexdigest()[:16]
        event_key = f"requirement.index:{requirement.id}:{digest}"
        event_exists = await db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_key == event_key))
        if event_exists is None:
            enqueue_index_event(
                db,
                event_key=event_key,
                event_type=REQUIREMENT_INDEX_REQUESTED,
                aggregate_type="requirement",
                aggregate_id=requirement.id,
            )
        imported_ids.append(str(requirement.id))

    run.status = "completed"
    run.result = {
        "fetched_count": len(issues),
        "created_count": created_count,
        "updated_count": updated_count,
        "requirement_ids": imported_ids,
    }
    run.completed_at = datetime.utcnow()
    db.add(
        AuditLog(
            entity_type="integration",
            entity_id=run.id,
            action="jira_import_completed",
            actor=actor,
            details={
                "project_id": str(payload.project_id),
                "fetched_count": len(issues),
                "created_count": created_count,
                "updated_count": updated_count,
            },
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
    actor = current_principal().username
    await _ensure_project(db, payload.project_id)
    await _require_project_access(db, payload.project_id, {"approver", "admin"})
    if not payload.repository.strip():
        raise HTTPException(status_code=422, detail="Repository name is required")
    result = await db.execute(
        select(TestCase)
        .join(Requirement, Requirement.id == TestCase.requirement_id)
        .where(
            Requirement.project_id == payload.project_id,
            TestCase.status == "approved",
        )
        .options(selectinload(TestCase.steps))
    )
    test_cases = result.scalars().all()
    run = RepositorySyncRun(
        repository=payload.repository,
        branch=payload.branch,
        status="queued" if test_cases else "completed",
        synced_count=0,
        vector_synced_count=0,
        requested_by=actor,
        details={
            "mode": "durable-http-repository-delivery",
            "project_id": str(payload.project_id),
            "queued_count": len(test_cases),
            "test_case_ids": [str(test_case.id) for test_case in test_cases],
        },
        completed_at=None if test_cases else datetime.utcnow(),
    )
    db.add(run)
    await db.flush()
    repository_digest = hashlib.sha256(
        f"{payload.repository.strip()}\n{payload.branch.strip()}".encode("utf-8")
    ).hexdigest()[:16]
    for test_case in test_cases:
        delivery_key = f"test_case:{test_case.id}:v{test_case.version}:repo:{repository_digest}"
        enqueue_outbox_event(
            db,
            event_key=f"repository.delivery:{run.id}:{test_case.id}",
            event_type=TEST_CASE_REPOSITORY_SYNC_REQUESTED,
            aggregate_type="test_case",
            aggregate_id=test_case.id,
            payload={"sync_run_id": str(run.id), "delivery_key": delivery_key},
        )
        test_case.repository_status = "pending_sync"
        test_case.repository_synced_at = None
    db.add(
        AuditLog(
            entity_type="repository_sync",
            entity_id=run.id,
            action="test_repository_sync_queued",
            actor=actor,
            details={
                "project_id": str(payload.project_id),
                "repository": payload.repository,
                "branch": payload.branch,
                "queued_count": len(test_cases),
            },
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
    require_global_role("admin")
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
    require_global_role("admin")
    result = await db.execute(select(RepositorySyncRun).order_by(RepositorySyncRun.started_at.desc()))
    return result.scalars().all()


@api_router.post(
    "/executions",
    response_model=list[TestExecutionRunSummary],
    tags=["Execution"],
)
async def queue_test_executions(
    payload: TestExecutionRequest,
    db: AsyncSession = Depends(get_db),
) -> list[TestExecutionRunSummary]:
    actor = current_principal().username
    await _ensure_project(db, payload.project_id)
    await _require_project_access(db, payload.project_id, {"approver", "admin"})
    environment = payload.environment.strip()
    if not environment:
        raise HTTPException(status_code=422, detail="Execution environment is required")
    test_case_ids = list(dict.fromkeys(payload.test_case_ids))
    result = await db.execute(
        select(TestCase)
        .join(Requirement, Requirement.id == TestCase.requirement_id)
        .where(
            Requirement.project_id == payload.project_id,
            TestCase.id.in_(test_case_ids),
            TestCase.status == "approved",
        )
    )
    test_cases = {test_case.id: test_case for test_case in result.scalars().all()}
    if len(test_cases) != len(test_case_ids):
        raise HTTPException(status_code=404, detail="One or more approved test cases were not found")

    runs: list[TestExecutionRun] = []
    for test_case_id in test_case_ids:
        test_case = test_cases[test_case_id]
        idempotency_key = f"execution:{payload.request_id}:{test_case.id}:v{test_case.version}"
        existing = await db.scalar(
            select(TestExecutionRun).where(TestExecutionRun.idempotency_key == idempotency_key)
        )
        if existing:
            runs.append(existing)
            continue
        run = TestExecutionRun(
            project_id=payload.project_id,
            test_case_id=test_case.id,
            test_case_version=test_case.version,
            environment=environment,
            runner="generic",
            status="queued",
            idempotency_key=idempotency_key,
            result={},
            requested_by=actor,
        )
        db.add(run)
        await db.flush()
        enqueue_outbox_event(
            db,
            event_key=f"execution.run:{run.id}",
            event_type=TEST_CASE_EXECUTION_REQUESTED,
            aggregate_type="test_execution_run",
            aggregate_id=run.id,
        )
        runs.append(run)

    db.add(
        AuditLog(
            entity_type="project",
            entity_id=payload.project_id,
            action="test_executions_queued",
            actor=actor,
            details={
                "request_id": str(payload.request_id),
                "environment": environment,
                "run_ids": [str(run.id) for run in runs],
            },
        )
    )
    await db.commit()
    for run in runs:
        await db.refresh(run)
    return runs


@api_router.get(
    "/executions",
    response_model=list[TestExecutionRunSummary],
    tags=["Execution"],
)
async def list_test_executions(
    project_id: uuid.UUID,
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[TestExecutionRunSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    stmt = select(TestExecutionRun).where(TestExecutionRun.project_id == project_id)
    if status:
        if status not in {"queued", "running", "passed", "failed", "error", "cancelled"}:
            raise HTTPException(status_code=422, detail="Unsupported execution status")
        stmt = stmt.where(TestExecutionRun.status == status)
    result = await db.execute(stmt.order_by(TestExecutionRun.created_at.desc()).limit(limit))
    return result.scalars().all()


@api_router.get(
    "/executions/candidates",
    response_model=list[TestCaseSummary],
    tags=["Execution"],
)
async def list_execution_candidates(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[TestCaseSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    result = await db.execute(
        select(TestCase)
        .join(Requirement, Requirement.id == TestCase.requirement_id)
        .where(Requirement.project_id == project_id, TestCase.status == "approved")
        .options(selectinload(TestCase.steps))
        .order_by(TestCase.title.asc())
    )
    return result.scalars().unique().all()


@api_router.get(
    "/executions/{run_id}",
    response_model=TestExecutionRunSummary,
    tags=["Execution"],
)
async def get_test_execution(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TestExecutionRunSummary:
    run = await db.get(TestExecutionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found")
    await _require_project_access(db, run.project_id)
    return run


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
    actor = current_principal().username
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
        requested_by=actor,
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="evaluation",
            entity_id=run.id,
            action="evaluation_suite_completed",
            actor=actor,
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
    require_global_role("admin")
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
    require_global_role("admin")
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
        "outbox_pending": (
            await db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "pending"))
        ).scalar_one(),
        "outbox_failed": (
            await db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "failed"))
        ).scalar_one(),
    }
    for name, value in metrics.items():
        db.add(OperationalMetric(metric_name=name, metric_value=int(value), dimensions={"source": "summary"}))
    await db.commit()
    return MonitoringSummary(status="ok", metrics=metrics, captured_at=datetime.utcnow())


@api_router.get(
    "/operations/dependencies",
    response_model=DependencyHealthSummary,
    tags=["Monitoring"],
)
async def dependency_health() -> DependencyHealthSummary:
    require_global_role("admin")
    probes = await probe_external_dependencies()
    statuses = [
        DependencyStatusSummary(name=probe.name, status=probe.status, configured=probe.configured)
        for probe in probes
    ]
    overall = "healthy" if all(item.status == "healthy" for item in statuses) else "degraded"
    return DependencyHealthSummary(status=overall, dependencies=statuses, checked_at=datetime.utcnow())


@api_router.get(
    "/operations/outbox",
    response_model=list[OutboxEventSummary],
    tags=["Monitoring"],
)
async def list_outbox_events(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[OutboxEventSummary]:
    require_global_role("admin")
    stmt = select(OutboxEvent)
    if status:
        if status not in {"pending", "processing", "completed", "failed"}:
            raise HTTPException(status_code=422, detail="Unsupported outbox status")
        stmt = stmt.where(OutboxEvent.status == status)
    result = await db.execute(stmt.order_by(OutboxEvent.created_at.desc()).limit(limit))
    return result.scalars().all()


@api_router.post(
    "/operations/outbox/{event_id}/retry",
    response_model=OutboxEventSummary,
    tags=["Monitoring"],
)
async def retry_outbox_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> OutboxEventSummary:
    principal = require_global_role("admin")
    event = await db.get(OutboxEvent, event_id, with_for_update=True)
    if not event:
        raise HTTPException(status_code=404, detail="Outbox event not found")
    if event.status in {"processing", "completed"}:
        raise HTTPException(status_code=409, detail=f"A {event.status} event cannot be retried")
    if event.status == "failed":
        event.status = "pending"
        event.attempts = 0
        event.available_at = datetime.utcnow()
        event.locked_at = None
        event.locked_by = None
        event.processed_at = None
        event.last_error = None
        db.add(
            AuditLog(
                entity_type="outbox_event",
                entity_id=event.id,
                action="outbox_event_retry_requested",
                actor=principal.username,
                details={"event_type": event.event_type, "aggregate_id": str(event.aggregate_id)},
            )
        )
        await db.commit()
        await db.refresh(event)
    return event


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
    actor = current_principal().username
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
            created_by=actor,
        )
        db.add(policy)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="governance_policy",
            entity_id=policy.id,
            action="governance_policy_created",
            actor=actor,
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
    require_global_role("admin")
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

    await _require_target_access(db, target_level, target_uuid)

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

    await _require_target_access(db, target_level, target_uuid)
    issues = await _collect_validation_issues(db, target_level, target_uuid)
    evaluation = await _record_quality_evaluation(
        db,
        target_level,
        target_uuid,
        issues,
        current_principal().username,
    )
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
    if target_level and target_id:
        await _require_target_access(db, target_level, target_id)
    elif current_principal().role != "admin":
        raise HTTPException(status_code=422, detail="target_level and target_id are required")
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

    await _require_requirement_access(db, requirement_uuid)

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

    await _require_requirement_access(db, scenario.requirement_id)

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

    await _require_requirement_access(db, test_case.requirement_id)

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

    await _require_requirement_access(db, requirement_uuid)

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

    try:
        generation_service = build_generation_service()
        generation_result = await generation_service.generate(
            requirement_id=str(requirement.id),
            project_id=str(requirement.project_id) if requirement.project_id else None,
            title=requirement.title,
            description=requirement.description,
            external_id=requirement.external_id,
        )
    except GenerationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    for generated_scenario in generation_result.draft.scenarios:
        scenario = TestScenario(
            requirement_id=requirement.id,
            title=generated_scenario.title,
            description=generated_scenario.description,
            priority=generated_scenario.priority,
            severity=generated_scenario.severity,
            category=generated_scenario.category,
            type=generated_scenario.type,
            status="draft",
        )
        db.add(scenario)
        await db.flush()

        for generated_case in generated_scenario.test_cases:
            test_case = TestCase(
                scenario_id=scenario.id,
                requirement_id=requirement.id,
                title=generated_case.title,
                description=generated_case.description,
                prerequisite=generated_case.prerequisite,
                priority=generated_case.priority,
                severity=generated_case.severity,
                category=generated_case.category,
                type=generated_case.type,
                status="draft",
            )
            db.add(test_case)
            await db.flush()

            for generated_step in generated_case.steps:
                db.add(
                    TestCaseStepModel(
                        test_case_id=test_case.id,
                        step_number=generated_step.step_number,
                        action=generated_step.action,
                        expected_result=generated_step.expected_result,
                    )
                )

    requirement.status = "generated"
    requirement.vector_id = generation_result.requirement_vector_id
    db.add(
        AuditLog(
            entity_type="requirement",
            entity_id=requirement.id,
            action="rag_generation_completed",
            actor=current_principal().username,
            details={
                "model": generation_result.model,
                "scenario_count": len(generation_result.draft.scenarios),
                "retrieved_vector_ids": [item.id for item in generation_result.retrieved_context],
            },
        )
    )
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
