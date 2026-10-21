import uuid
import re
import hashlib
import json
from difflib import SequenceMatcher
from time import perf_counter
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.core.config import settings
from app.core.security import current_principal, require_global_role
from app.models import (
    Alert,
    ApprovalRecord,
    AuditLog,
    EvaluationRun,
    Feedback,
    GovernancePolicy,
    ImpactAnalysis,
    IntegrationRun,
    IntegrationSchedule,
    ImportMappingProfile,
    MappedImportJob,
    OperationalMetric,
    OutboxEvent,
    Project,
    ProjectMembership,
    QualityEvaluation,
    Requirement,
    SavedSearch,
    SearchEvent,
    SearchJudgment,
    RepositorySyncRun,
    RevisionRecord,
    SemanticCalibrationRun,
    TestCase,
    TestCaseStep as TestCaseStepModel,
    TestCaseVersion,
    TestExecutionRun,
    TestScenario,
    UnresolvedImportRecord,
    User,
    RequirementVersion,
)
from app.schemas import (
    AlertSummary,
    ApprovalAction,
    ApprovalRecordSummary,
    AuditLogSummary,
    CleanupRequest,
    CleanupResult,
    ComplianceEvidenceExport,
    ComplianceProfileSummary,
    ComplianceProfileUpdate,
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
    IntegrationScheduleCreate,
    IntegrationScheduleSummary,
    ImportMappingProfileCreate,
    ImportMappingProfileUpdate,
    ImportMappingProfileSummary,
    MappedImportPreview,
    MappedImportJobSummary,
    UnresolvedImportRecordSummary,
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
    SavedSearchCreate,
    SavedSearchSummary,
    SearchAnalyticsSummary,
    CustomFieldFacetSummary,
    SearchJudgmentCreate,
    SearchJudgmentSummary,
    SemanticCalibrationRequest,
    SemanticCalibrationSummary,
    RequirementCreate,
    RequirementDetail,
    RequirementVersionSummary,
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
    RetrievedContext,
    build_generation_service,
)
from app.services.outbox import (
    FEEDBACK_INDEX_REQUESTED,
    REQUIREMENT_VERSION_INDEX_REQUESTED,
    TEST_CASE_VERSION_INDEX_REQUESTED,
    TEST_CASE_REPOSITORY_SYNC_REQUESTED,
    TEST_CASE_EXECUTION_REQUESTED,
    enqueue_outbox_event,
    enqueue_index_event,
)
from app.services.impact import build_semantic_impact_service
from app.services.integrations import (
    IntegrationConfigurationError,
    IntegrationProviderError,
)
from app.services.jira_sync import clean_requirement_text, sync_jira_requirements
from app.services.file_ingestion import FileIngestionError, parse_requirement_file
from app.services.historical_ingestion import (
    HistoricalIngestionError,
    parse_historical_test_case_file,
)
from app.services.historical_import import (
    HistoricalImportConflictError,
    import_historical_test_cases,
)
from app.services.mapped_ingestion import (
    MappedIngestionError,
    map_import_file,
    validate_mapping_configuration,
)
from app.services.health import probe_external_dependencies
from app.services.search import KeywordSearchService, build_semantic_search_service, fuse_search_matches
from app.services.calibration import CalibrationSample, calibrate_thresholds
from app.services.versioning import snapshot_requirement
from app.services.unresolved_imports import resolve_unresolved_records, stage_unresolved_test_cases

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


async def _generation_keyword_contexts(
    db: AsyncSession,
    *,
    query: str,
    project_id: uuid.UUID | None,
) -> list[RetrievedContext]:
    if project_id is None:
        return []
    matches = await KeywordSearchService(db).search(
        query,
        project_id=str(project_id),
        limit=settings.rag_candidate_limit,
    )
    return [
        RetrievedContext(
            id=match.vector_id,
            score=match.keyword_score if match.keyword_score is not None else match.score,
            text=match.text,
            metadata={
                **match.metadata,
                "entity_type": match.entity_type,
                "entity_id": match.entity_id,
                "title": match.title,
                "retrieval_source": "keyword",
            },
        )
        for match in matches
    ]


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
    return clean_requirement_text(text)


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
    duplicate_threshold, update_threshold = await _impact_thresholds(db, project_id)
    scoring_rules = await _impact_scoring_rules(db, project_id)
    change_evidence = await _requirement_change_evidence(db, requirement_id)
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
    deprecation_keywords = {
        str(item).strip().lower()
        for item in scoring_rules["deprecation_keywords"]
        if str(item).strip()
    }

    for match in matches:
        score = match.score
        keyword_overlap = source_tokens & deprecation_keywords
        try:
            if score >= duplicate_threshold:
                duplicates.append(
                    _semantic_candidate(
                        match.metadata,
                        score,
                        "archive_duplicate",
                        f"Semantic similarity is at or above the {round(duplicate_threshold * 100)}% duplicate threshold.",
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
            elif score >= update_threshold:
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

    coverage_score, risk_score, score_evidence = _evidence_scores(
        duplicates,
        deprecations,
        updates,
        change_evidence=change_evidence,
        rules=scoring_rules,
    )
    summary = {
        "approved_cases_scanned": len(matches),
        "duplicate_count": len(duplicates),
        "deprecation_count": len(deprecations),
        "update_count": len(updates),
        "manual_review_recommended": bool(deprecations or updates or risk_score >= 40),
        "thresholds": {"duplicate": duplicate_threshold, "update": update_threshold},
        "similarity_mode": "embedding_cosine",
        "requirement_change": change_evidence,
        "score_evidence": score_evidence,
        "scoring_policy": scoring_rules,
    }

    analysis = ImpactAnalysis(
        requirement_id=requirement_id,
        source_text=source_text,
        similarity_threshold=int(duplicate_threshold * 100),
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
        similarity_threshold=duplicate_threshold,
        duplicates=duplicates,
        deprecations=deprecations,
        updates=updates,
        risk_score=risk_score,
        coverage_score=coverage_score,
        summary=summary,
        created_by=created_by,
        created_at=analysis.created_at,
    )


async def _impact_thresholds(db: AsyncSession, project_id: uuid.UUID) -> tuple[float, float]:
    policy = await db.scalar(
        select(GovernancePolicy).where(
            GovernancePolicy.name == f"semantic-impact-thresholds:{project_id}",
            GovernancePolicy.status == "active",
        )
    )
    rules = policy.rules if policy and isinstance(policy.rules, dict) else {}
    try:
        duplicate = float(rules.get("duplicate", DUPLICATE_THRESHOLD))
        update = float(rules.get("update", UPDATE_THRESHOLD))
    except (TypeError, ValueError):
        return DUPLICATE_THRESHOLD, UPDATE_THRESHOLD
    if not 0 <= update < duplicate <= 1:
        return DUPLICATE_THRESHOLD, UPDATE_THRESHOLD
    return duplicate, update


DEFAULT_IMPACT_SCORING_RULES = {
    "duplicate_coverage_weight": 1.0,
    "update_coverage_weight": 0.65,
    "deprecation_coverage_weight": 0.35,
    "uncovered_risk": 40.0,
    "update_risk_weight": 18.0,
    "deprecation_risk_weight": 28.0,
    "critical_severity_risk": 12.0,
    "change_magnitude_risk": 20.0,
    "deprecation_keywords": sorted(DEPRECATION_KEYWORDS),
}


async def _impact_scoring_rules(db: AsyncSession, project_id: uuid.UUID) -> dict:
    policy = await db.scalar(
        select(GovernancePolicy).where(
            GovernancePolicy.name == f"impact-scoring:{project_id}",
            GovernancePolicy.status == "active",
        )
    )
    supplied = policy.rules if policy and isinstance(policy.rules, dict) else {}
    rules = {**DEFAULT_IMPACT_SCORING_RULES}
    for key, default in DEFAULT_IMPACT_SCORING_RULES.items():
        value = supplied.get(key, default)
        if key == "deprecation_keywords":
            if isinstance(value, list) and value:
                rules[key] = [str(item) for item in value[:100]]
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= numeric <= 100:
            rules[key] = numeric
    return rules


async def _requirement_change_evidence(
    db: AsyncSession,
    requirement_id: uuid.UUID | None,
) -> dict:
    if requirement_id is None:
        return {"available": False, "reason": "ad_hoc_text"}
    versions = list(
        (
            await db.execute(
                select(RequirementVersion)
                .where(RequirementVersion.requirement_id == requirement_id)
                .order_by(RequirementVersion.version.desc())
                .limit(2)
            )
        ).scalars()
    )
    if len(versions) < 2:
        return {
            "available": False,
            "reason": "no_previous_version",
            "current_version": versions[0].version if versions else None,
        }
    current, previous = versions[0], versions[1]
    previous_text = f"{previous.title}\n{previous.description}".strip()
    current_text = f"{current.title}\n{current.description}".strip()
    previous_tokens = _tokens(previous_text)
    current_tokens = _tokens(current_text)
    added = sorted(current_tokens - previous_tokens)
    removed = sorted(previous_tokens - current_tokens)
    similarity = SequenceMatcher(None, previous_text.lower(), current_text.lower()).ratio()
    return {
        "available": True,
        "previous_version": previous.version,
        "current_version": current.version,
        "text_similarity": round(similarity, 4),
        "change_magnitude": round(1.0 - similarity, 4),
        "added_token_count": len(added),
        "removed_token_count": len(removed),
        "added_token_sample": added[:25],
        "removed_token_sample": removed[:25],
        "deprecation_terms_added": sorted((current_tokens - previous_tokens) & DEPRECATION_KEYWORDS),
    }


def _evidence_scores(
    duplicates: list[ImpactCandidate],
    deprecations: list[ImpactCandidate],
    updates: list[ImpactCandidate],
    *,
    change_evidence: dict,
    rules: dict,
) -> tuple[int, int, dict]:
    weighted_coverage = [
        *(item.similarity * rules["duplicate_coverage_weight"] for item in duplicates),
        *(item.similarity * rules["update_coverage_weight"] for item in updates),
        *(item.similarity * rules["deprecation_coverage_weight"] for item in deprecations),
    ]
    best_coverage = max(weighted_coverage, default=0.0)
    breadth_bonus = min(0.15, max(0, len(weighted_coverage) - 1) * 0.03)
    coverage_score = round(min(1.0, best_coverage + breadth_bonus) * 100)

    uncovered = rules["uncovered_risk"] if not weighted_coverage else 0.0
    update_risk = sum(item.similarity for item in updates) * rules["update_risk_weight"]
    deprecation_risk = sum(item.similarity for item in deprecations) * rules["deprecation_risk_weight"]
    critical = (
        rules["critical_severity_risk"]
        if any((item.severity or "").lower() == "critical" for item in updates + deprecations)
        else 0.0
    )
    historical_change_risk = (
        float(change_evidence.get("change_magnitude", 0.0) or 0.0)
        * rules["change_magnitude_risk"]
    )
    risk_score = round(
        min(100.0, uncovered + update_risk + deprecation_risk + critical + historical_change_risk)
    )
    return coverage_score, risk_score, {
        "coverage": {
            "best_weighted_similarity": round(best_coverage, 4),
            "breadth_bonus": round(breadth_bonus, 4),
            "candidate_count": len(weighted_coverage),
        },
        "risk": {
            "uncovered": round(uncovered, 2),
            "updates": round(update_risk, 2),
            "deprecations": round(deprecation_risk, 2),
            "critical_severity": round(critical, 2),
            "historical_change": round(historical_change_risk, 2),
        },
    }


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
) -> TestCaseVersion:
    version = TestCaseVersion(
        test_case_id=test_case.id,
        requirement_id=test_case.requirement_id,
        scenario_id=test_case.scenario_id,
        version=test_case.version,
        external_id=test_case.external_id,
        source=test_case.source,
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
        vector_id=f"test_case:{test_case.id}:v{test_case.version}",
    )
    db.add(version)
    await db.flush()
    return version


async def _snapshot_requirement_and_enqueue(
    db: AsyncSession,
    requirement: Requirement,
) -> RequirementVersion:
    version = await snapshot_requirement(db, requirement)
    if requirement.project_id is not None:
        enqueue_index_event(
            db,
            event_key=f"requirement_version.index:{version.id}",
            event_type=REQUIREMENT_VERSION_INDEX_REQUESTED,
            aggregate_type="requirement_version",
            aggregate_id=version.id,
            payload={"requirement_id": str(requirement.id), "version": requirement.version},
        )
    return version


async def _search_tuning(db: AsyncSession, project_id: uuid.UUID, query: str) -> tuple[list[str], int]:
    policy = await db.scalar(
        select(GovernancePolicy).where(
            GovernancePolicy.name == f"search-tuning:{project_id}",
            GovernancePolicy.status == "active",
        )
    )
    rules = policy.rules if policy and isinstance(policy.rules, dict) else {}
    synonym_map = rules.get("synonyms", {})
    aliases: list[str] = []
    if isinstance(synonym_map, dict):
        query_tokens = _tokens(query)
        for key, values in synonym_map.items():
            if str(key).lower() not in query_tokens or not isinstance(values, list):
                continue
            aliases.extend(str(item).strip() for item in values if str(item).strip())
    try:
        rank_constant = int(rules.get("rrf_rank_constant", 60))
    except (TypeError, ValueError):
        rank_constant = 60
    return list(dict.fromkeys(aliases))[:20], min(200, max(1, rank_constant))


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
    await _snapshot_requirement_and_enqueue(db, requirement)
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


@api_router.get(
    "/requirements/{requirement_id}/versions",
    response_model=list[RequirementVersionSummary],
    tags=["Requirements"],
)
async def get_requirement_versions(
    requirement_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[RequirementVersionSummary]:
    try:
        requirement_uuid = uuid.UUID(requirement_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Requirement not found")
    await _require_requirement_access(db, requirement_uuid)
    result = await db.execute(
        select(RequirementVersion)
        .where(RequirementVersion.requirement_id == requirement_uuid)
        .order_by(RequirementVersion.version.desc())
    )
    return result.scalars().all()


async def _create_approval_record(
    db: AsyncSession,
    target_level: str,
    target_id: uuid.UUID,
    status: str,
    version: int,
    approved_by: str,
    notes: str | None = None,
) -> None:
    project_id = await _target_project_id(db, target_level, target_id)
    if project_id is not None:
        profile, _ = await _compliance_profile(db, project_id)
        if profile.approval_notes_required and not (notes or "").strip():
            raise HTTPException(status_code=422, detail="This project's compliance profile requires approval notes")
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


async def _target_project_id(
    db: AsyncSession, target_level: str, target_id: uuid.UUID
) -> uuid.UUID | None:
    if target_level == "requirement":
        return await db.scalar(select(Requirement.project_id).where(Requirement.id == target_id))
    if target_level == "scenario":
        return await db.scalar(
            select(Requirement.project_id)
            .join(TestScenario, TestScenario.requirement_id == Requirement.id)
            .where(TestScenario.id == target_id)
        )
    if target_level == "test_case":
        return await db.scalar(
            select(Requirement.project_id)
            .join(TestCase, TestCase.requirement_id == Requirement.id)
            .where(TestCase.id == target_id)
        )
    return None


async def _compliance_profile(
    db: AsyncSession, project_id: uuid.UUID
) -> tuple[ComplianceProfileSummary, GovernancePolicy | None]:
    policy = await db.scalar(
        select(GovernancePolicy).where(
            GovernancePolicy.name == f"compliance-profile:{project_id}",
            GovernancePolicy.status == "active",
        )
    )
    rules = policy.rules if policy and isinstance(policy.rules, dict) else {}
    try:
        retention_days = int(rules.get("evidence_retention_days", 365))
    except (TypeError, ValueError):
        retention_days = 365
    raw_frameworks = rules.get("frameworks", [])
    if not isinstance(raw_frameworks, list):
        raw_frameworks = []
    profile = ComplianceProfileSummary(
        project_id=project_id,
        frameworks=[str(item) for item in raw_frameworks][:10],
        evidence_retention_days=min(3650, max(30, retention_days)),
        evidence_export_enabled=bool(rules.get("evidence_export_enabled", True)),
        pseudonymize_actors=bool(rules.get("pseudonymize_actors", True)),
        approval_notes_required=bool(rules.get("approval_notes_required", False)),
        updated_at=policy.updated_at if policy else None,
    )
    return profile, policy


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
    test_case.vector_id = f"test_case:{test_case.id}:v{test_case.version}"
    actor = _actor(payload)
    version = await _create_test_case_version(db, test_case, actor, payload.notes)
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
        event_key=f"test_case_version.index:{version.id}",
        event_type=TEST_CASE_VERSION_INDEX_REQUESTED,
        aggregate_type="test_case_version",
        aggregate_id=version.id,
        payload={"test_case_id": str(test_case.id), "version": test_case.version},
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
            feedback_query = (
                f"Requirement title: {requirement.title}\nRequirement description: {requirement.description}\n"
                f"Current target: {target_context}\nReviewer feedback: {feedback.comment}"
            )
            generation_result = await build_generation_service().generate_from_feedback(
                requirement_id=str(requirement.id),
                project_id=str(requirement.project_id) if requirement.project_id else None,
                title=requirement.title,
                description=requirement.description,
                external_id=requirement.external_id,
                feedback_text=feedback.comment,
                target_context=str(target_context),
                action=action,
                requirement_version=requirement.version,
                keyword_contexts=await _generation_keyword_contexts(
                    db,
                    query=feedback_query,
                    project_id=requirement.project_id,
                ),
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
    offset: int = Query(0, ge=0, le=5000),
    custom_field: str | None = Query(None, min_length=1, max_length=100),
    custom_value: str | None = Query(None, max_length=500),
    mode: Literal["semantic", "keyword", "hybrid"] = Query("semantic"),
    db: AsyncSession = Depends(get_db),
) -> list[SemanticSearchResult]:
    await _ensure_project(db, project_id)
    custom_field = custom_field if isinstance(custom_field, str) else None
    custom_value = custom_value if isinstance(custom_value, str) else None
    if entity_type and entity_type not in {"requirement", "test_case", "feedback"}:
        raise HTTPException(status_code=422, detail="Unsupported semantic search entity type")
    if bool(custom_field) != (custom_value is not None):
        raise HTTPException(status_code=422, detail="custom_field and custom_value must be supplied together")
    if custom_field and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}", custom_field):
        raise HTTPException(status_code=422, detail="custom_field contains unsupported characters")
    started = perf_counter()
    aliases, rank_constant = await _search_tuning(db, project_id, query)
    page_end = offset + limit
    candidate_limit = min(page_end * 4, 400) if mode == "hybrid" else limit
    keyword_matches = []
    if mode in {"keyword", "hybrid"}:
        keyword_matches = await KeywordSearchService(db).search(
            query.strip(),
            project_id=str(project_id),
            entity_type=entity_type,
            limit=candidate_limit,
            offset=0 if mode == "hybrid" else offset,
            aliases=aliases,
            custom_field=custom_field,
            custom_value=custom_value,
        )
    semantic_matches = []
    semantic_fallback = False
    if mode in {"semantic", "hybrid"}:
        try:
            semantic_matches = await build_semantic_search_service().search(
                query.strip(),
                project_id=str(project_id),
                entity_type=entity_type,
                limit=candidate_limit,
                offset=0 if mode == "hybrid" else offset,
                custom_field=custom_field,
                custom_value=custom_value,
            )
        except GenerationConfigurationError as exc:
            if mode == "hybrid":
                semantic_fallback = True
            else:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        except GenerationProviderError as exc:
            if mode == "hybrid":
                semantic_fallback = True
            else:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
    if mode == "hybrid":
        all_matches = (
            keyword_matches
            if semantic_fallback
            else fuse_search_matches(
                semantic_matches,
                keyword_matches,
                limit=page_end,
                rank_constant=rank_constant,
            )
        )
        matches = all_matches[offset:page_end]
    elif mode == "keyword":
        matches = keyword_matches[:limit]
    else:
        matches = semantic_matches[:limit]
    event = SearchEvent(
        project_id=project_id,
        query=query.strip(),
        mode=mode,
        entity_type=entity_type,
        result_count=len(matches),
        offset=offset,
        latency_ms=max(0, round((perf_counter() - started) * 1000)),
        semantic_fallback=semantic_fallback,
        requested_by=current_principal().username,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return [
        SemanticSearchResult(
            vector_id=match.vector_id,
            entity_type=match.entity_type,
            entity_id=match.entity_id,
            title=match.title,
            text=match.text,
            score=round(match.score, 4),
            metadata={
                **match.metadata,
                "search_event_id": str(event.id),
                "result_rank": offset + index,
                "offset": offset,
                **({"custom_field": custom_field, "custom_value": custom_value} if custom_field else {}),
                **({"semantic_fallback": True} if semantic_fallback else {}),
            },
            search_mode="keyword" if semantic_fallback else mode,
            semantic_score=round(match.semantic_score, 4) if match.semantic_score is not None else None,
            keyword_score=round(match.keyword_score, 4) if match.keyword_score is not None else None,
            matched_fields=list(match.matched_fields),
        )
        for index, match in enumerate(matches, start=1)
    ]


@api_router.post(
    "/search/judgments",
    response_model=SearchJudgmentSummary,
    tags=["Search"],
)
async def record_search_judgment(
    payload: SearchJudgmentCreate,
    db: AsyncSession = Depends(get_db),
) -> SearchJudgmentSummary:
    event = await db.get(SearchEvent, payload.search_event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Search event not found")
    await _require_project_access(db, event.project_id)
    actor = current_principal().username
    judgment = await db.scalar(
        select(SearchJudgment).where(
            SearchJudgment.search_event_id == payload.search_event_id,
            SearchJudgment.entity_type == payload.entity_type,
            SearchJudgment.entity_id == payload.entity_id,
        )
    )
    if judgment is None:
        judgment = SearchJudgment(
            **payload.model_dump(),
            created_by=actor,
        )
        db.add(judgment)
    else:
        judgment.rank = payload.rank
        judgment.judgment = payload.judgment
        judgment.created_by = actor
    await db.commit()
    await db.refresh(judgment)
    return judgment


@api_router.post(
    "/search/saved",
    response_model=SavedSearchSummary,
    tags=["Search"],
)
async def save_search(
    payload: SavedSearchCreate,
    db: AsyncSession = Depends(get_db),
) -> SavedSearchSummary:
    await _ensure_project(db, payload.project_id)
    await _require_project_access(db, payload.project_id)
    actor = current_principal().username
    saved = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.project_id == payload.project_id,
            SavedSearch.created_by == actor,
            SavedSearch.name == payload.name.strip(),
        )
    )
    if saved is None:
        saved = SavedSearch(created_by=actor, **payload.model_dump())
        db.add(saved)
    else:
        saved.query = payload.query.strip()
        saved.mode = payload.mode
        saved.entity_type = payload.entity_type
        saved.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(saved)
    return saved


@api_router.get(
    "/search/saved",
    response_model=list[SavedSearchSummary],
    tags=["Search"],
)
async def list_saved_searches(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[SavedSearchSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    result = await db.execute(
        select(SavedSearch)
        .where(
            SavedSearch.project_id == project_id,
            SavedSearch.created_by == current_principal().username,
        )
        .order_by(SavedSearch.name.asc())
    )
    return list(result.scalars())


@api_router.delete("/search/saved/{saved_search_id}", status_code=204, tags=["Search"])
async def delete_saved_search(
    saved_search_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    saved = await db.get(SavedSearch, saved_search_id)
    if saved is None or saved.created_by != current_principal().username:
        raise HTTPException(status_code=404, detail="Saved search not found")
    await _require_project_access(db, saved.project_id)
    await db.delete(saved)
    await db.commit()


@api_router.get(
    "/search/analytics",
    response_model=SearchAnalyticsSummary,
    tags=["Search"],
)
async def get_search_analytics(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SearchAnalyticsSummary:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"approver", "admin"})
    query_count, zero_count, fallback_count, average_latency = (
        await db.execute(
            select(
                func.count(SearchEvent.id),
                func.count(SearchEvent.id).filter(SearchEvent.result_count == 0),
                func.count(SearchEvent.id).filter(SearchEvent.semantic_fallback.is_(True)),
                func.coalesce(func.avg(SearchEvent.latency_ms), 0),
            ).where(SearchEvent.project_id == project_id)
        )
    ).one()
    judgment_rows = (
        await db.execute(
            select(SearchJudgment.judgment, func.count(SearchJudgment.id))
            .join(SearchEvent, SearchEvent.id == SearchJudgment.search_event_id)
            .where(SearchEvent.project_id == project_id)
            .group_by(SearchJudgment.judgment)
        )
    ).all()
    top_rows = (
        await db.execute(
            select(SearchEvent.query, func.count(SearchEvent.id).label("count"))
            .where(SearchEvent.project_id == project_id)
            .group_by(SearchEvent.query)
            .order_by(text("count DESC"), SearchEvent.query.asc())
            .limit(10)
        )
    ).all()
    return SearchAnalyticsSummary(
        project_id=project_id,
        query_count=int(query_count or 0),
        zero_result_count=int(zero_count or 0),
        fallback_count=int(fallback_count or 0),
        average_latency_ms=round(float(average_latency or 0), 2),
        judgments={name: count for name, count in judgment_rows},
        top_queries=[{"query": query, "count": count} for query, count in top_rows],
    )


@api_router.get(
    "/search/custom-field-facets",
    response_model=CustomFieldFacetSummary,
    tags=["Search"],
)
async def get_custom_field_facets(
    project_id: uuid.UUID,
    field: str = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> CustomFieldFacetSummary:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}", field):
        raise HTTPException(status_code=422, detail="field contains unsupported characters")
    rows = (
        await db.execute(
            text(
                """
                SELECT value, count(*) AS count
                FROM (
                  SELECT metadata -> 'custom_fields' ->> :field AS value
                  FROM requirements
                  WHERE project_id = :project_id
                  UNION ALL
                  SELECT tc.custom_fields ->> :field AS value
                  FROM test_cases tc
                  JOIN requirements r ON r.id = tc.requirement_id
                  WHERE r.project_id = :project_id
                ) values
                WHERE value IS NOT NULL AND value <> ''
                GROUP BY value
                ORDER BY count DESC, value ASC
                LIMIT 100
                """
            ),
            {"project_id": project_id, "field": field},
        )
    ).all()
    return CustomFieldFacetSummary(
        field=field,
        values=[{"value": value, "count": count} for value, count in rows],
    )


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


async def _apply_semantic_calibration(
    db: AsyncSession,
    calibration: SemanticCalibrationRun,
    actor: str,
) -> None:
    if calibration.status == "applied":
        return
    policy_name = f"semantic-impact-thresholds:{calibration.project_id}"
    policy = await db.scalar(select(GovernancePolicy).where(GovernancePolicy.name == policy_name))
    rules = {
        **calibration.proposed_thresholds,
        "calibration_run_id": str(calibration.id),
        "dataset_digest": calibration.dataset_digest,
        "sample_count": calibration.sample_count,
        "metrics": calibration.metrics,
    }
    if policy:
        policy.rules = rules
        policy.status = "active"
        policy.updated_at = datetime.utcnow()
    else:
        db.add(
            GovernancePolicy(
                name=policy_name,
                policy_type="semantic_impact_thresholds",
                rules=rules,
                status="active",
                created_by=actor,
            )
        )
    calibration.status = "applied"
    calibration.applied_at = datetime.utcnow()
    db.add(
        AuditLog(
            entity_type="semantic_calibration",
            entity_id=calibration.id,
            action="semantic_thresholds_applied",
            actor=actor,
            details={
                "project_id": str(calibration.project_id),
                "dataset_digest": calibration.dataset_digest,
                "thresholds": calibration.proposed_thresholds,
                "metrics": calibration.metrics,
            },
        )
    )


@api_router.post(
    "/impact/calibrations",
    response_model=SemanticCalibrationSummary,
    tags=["Impact"],
)
async def create_semantic_calibration(
    payload: SemanticCalibrationRequest,
    db: AsyncSession = Depends(get_db),
) -> SemanticCalibrationSummary:
    await _ensure_project(db, payload.project_id)
    await _require_project_access(db, payload.project_id, {"approver", "admin"})
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"semantic-calibration:{payload.project_id}"},
    )
    actor = current_principal().username
    samples = [
        CalibrationSample(similarity=item.similarity, expected_action=item.expected_action.strip().lower())
        for item in payload.samples
    ]
    try:
        result = calibrate_thresholds(samples)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    canonical_samples = sorted((round(item.similarity, 6), item.expected_action) for item in samples)
    dataset_digest = hashlib.sha256(
        json.dumps(canonical_samples, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    calibration = await db.scalar(
        select(SemanticCalibrationRun).where(
            SemanticCalibrationRun.project_id == payload.project_id,
            SemanticCalibrationRun.dataset_digest == dataset_digest,
        )
    )
    if calibration is None:
        duplicate_threshold, update_threshold = await _impact_thresholds(db, payload.project_id)
        calibration = SemanticCalibrationRun(
            project_id=payload.project_id,
            dataset_digest=dataset_digest,
            sample_count=len(samples),
            label_distribution=result.label_distribution,
            previous_thresholds={"duplicate": duplicate_threshold, "update": update_threshold},
            proposed_thresholds={
                "duplicate": result.duplicate_threshold,
                "update": result.update_threshold,
            },
            metrics={
                "accuracy": result.accuracy,
                "macro_f1": result.macro_f1,
                "confusion": result.confusion,
            },
            status="proposed",
            requested_by=actor,
        )
        db.add(calibration)
        await db.flush()
        db.add(
            AuditLog(
                entity_type="semantic_calibration",
                entity_id=calibration.id,
                action="semantic_calibration_created",
                actor=actor,
                details={
                    "project_id": str(payload.project_id),
                    "dataset_digest": dataset_digest,
                    "sample_count": len(samples),
                    "proposed_thresholds": calibration.proposed_thresholds,
                    "metrics": calibration.metrics,
                },
            )
        )
    if payload.apply:
        await _apply_semantic_calibration(db, calibration, actor)
    await db.commit()
    await db.refresh(calibration)
    return calibration


@api_router.get(
    "/impact/calibrations",
    response_model=list[SemanticCalibrationSummary],
    tags=["Impact"],
)
async def list_semantic_calibrations(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[SemanticCalibrationSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    result = await db.execute(
        select(SemanticCalibrationRun)
        .where(SemanticCalibrationRun.project_id == project_id)
        .order_by(SemanticCalibrationRun.created_at.desc())
    )
    return result.scalars().all()


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
            await _snapshot_requirement_and_enqueue(db, requirement)
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
    "/test-cases/import-file",
    response_model=IntegrationRunSummary,
    tags=["TestCases"],
)
async def import_historical_test_case_file(
    project_id: uuid.UUID = Form(...),
    uploaded_file: UploadFile = File(..., alias="file"),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRunSummary:
    require_global_role("approver", "admin")
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"approver", "admin"})
    allowed_content_types = {
        "text/csv",
        "application/csv",
        "application/json",
        "application/octet-stream",
    }
    if uploaded_file.content_type and uploaded_file.content_type.lower() not in allowed_content_types:
        raise HTTPException(status_code=415, detail="Unsupported historical test-case file content type")
    content = await uploaded_file.read(settings.upload_max_bytes + 1)
    filename = uploaded_file.filename
    await uploaded_file.close()
    try:
        parsed = parse_historical_test_case_file(
            filename,
            content,
            max_bytes=settings.upload_max_bytes,
            max_test_cases=settings.upload_max_test_cases,
        )
        result = await import_historical_test_cases(
            db,
            project_id=project_id,
            items=parsed,
            actor=current_principal().username,
        )
    except HistoricalIngestionError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HistoricalImportConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = await db.get(IntegrationRun, result.run_id)
    if run is None:
        raise HTTPException(status_code=500, detail="Historical import evidence was not persisted")
    return run


@api_router.get(
    "/import-mappings",
    response_model=list[ImportMappingProfileSummary],
    tags=["Integrations"],
)
async def list_import_mapping_profiles(
    project_id: uuid.UUID,
    entity_type: Literal["requirement", "test_case"] | None = None,
    include_history: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[ImportMappingProfile]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    query = select(ImportMappingProfile).where(ImportMappingProfile.project_id == project_id)
    if entity_type:
        query = query.where(ImportMappingProfile.entity_type == entity_type)
    if not include_history:
        query = query.where(ImportMappingProfile.active.is_(True))
    result = await db.execute(
        query.order_by(
            ImportMappingProfile.entity_type,
            ImportMappingProfile.name,
            ImportMappingProfile.version.desc(),
        )
    )
    return list(result.scalars().all())


@api_router.post(
    "/import-mappings",
    response_model=ImportMappingProfileSummary,
    tags=["Integrations"],
)
async def create_import_mapping_profile(
    payload: ImportMappingProfileCreate,
    db: AsyncSession = Depends(get_db),
) -> ImportMappingProfile:
    require_global_role("approver", "admin")
    await _ensure_project(db, payload.project_id)
    await _require_project_access(db, payload.project_id, {"approver", "admin"})
    try:
        validate_mapping_configuration(payload.entity_type, payload.configuration)
    except MappedIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = (
        await db.execute(
            select(ImportMappingProfile).where(
                ImportMappingProfile.project_id == payload.project_id,
                ImportMappingProfile.entity_type == payload.entity_type,
                ImportMappingProfile.name == payload.name.strip(),
                ImportMappingProfile.active.is_(True),
            )
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="An import mapping profile with this name already exists")
    profile = ImportMappingProfile(
        project_id=payload.project_id,
        name=payload.name.strip(),
        entity_type=payload.entity_type,
        configuration=payload.configuration,
        active=payload.active,
        created_by=current_principal().username,
    )
    db.add(profile)
    await db.flush()
    db.add(AuditLog(
        entity_type="import_mapping_profile",
        entity_id=profile.id,
        action="import_mapping_profile_created",
        actor=current_principal().username,
        details={"project_id": str(payload.project_id), "entity_type": payload.entity_type, "name": profile.name},
    ))
    await db.commit()
    await db.refresh(profile)
    return profile


@api_router.put(
    "/import-mappings/{profile_id}",
    response_model=ImportMappingProfileSummary,
    tags=["Integrations"],
)
async def update_import_mapping_profile(
    profile_id: uuid.UUID,
    payload: ImportMappingProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> ImportMappingProfile:
    require_global_role("approver", "admin")
    profile = await db.get(ImportMappingProfile, profile_id)
    if not profile or not profile.active:
        raise HTTPException(status_code=404, detail="Import mapping profile not found")
    await _require_project_access(db, profile.project_id, {"approver", "admin"})
    try:
        validate_mapping_configuration(profile.entity_type, payload.configuration)
    except MappedIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate = (
        await db.execute(
            select(ImportMappingProfile).where(
                ImportMappingProfile.project_id == profile.project_id,
                ImportMappingProfile.entity_type == profile.entity_type,
                ImportMappingProfile.name == payload.name.strip(),
                ImportMappingProfile.id != profile.id,
                ImportMappingProfile.active.is_(True),
            )
        )
    ).scalars().first()
    if duplicate:
        raise HTTPException(status_code=409, detail="An import mapping profile with this name already exists")
    profile.active = False
    profile.superseded_at = datetime.utcnow()
    latest_version = await db.scalar(
        select(func.max(ImportMappingProfile.version)).where(
            ImportMappingProfile.project_id == profile.project_id,
            ImportMappingProfile.entity_type == profile.entity_type,
            ImportMappingProfile.name == payload.name.strip(),
        )
    )
    revision = ImportMappingProfile(
        project_id=profile.project_id,
        name=payload.name.strip(),
        entity_type=profile.entity_type,
        configuration=payload.configuration,
        version=int(latest_version or 0) + 1,
        parent_profile_id=profile.id,
        active=payload.active,
        created_by=current_principal().username,
    )
    db.add(revision)
    await db.flush()
    db.add(AuditLog(
        entity_type="import_mapping_profile",
        entity_id=revision.id,
        action="import_mapping_profile_updated",
        actor=current_principal().username,
        details={
            "project_id": str(profile.project_id),
            "name": revision.name,
            "version": revision.version,
            "supersedes": str(profile.id),
        },
    ))
    await db.commit()
    await db.refresh(revision)
    return revision


@api_router.post(
    "/import-mappings/{profile_id}/rollback",
    response_model=ImportMappingProfileSummary,
    tags=["Integrations"],
)
async def rollback_import_mapping_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ImportMappingProfile:
    require_global_role("approver", "admin")
    target = await db.get(ImportMappingProfile, profile_id)
    if not target:
        raise HTTPException(status_code=404, detail="Import mapping profile not found")
    await _require_project_access(db, target.project_id, {"approver", "admin"})
    latest = (
        await db.execute(
            select(ImportMappingProfile)
            .where(
                ImportMappingProfile.project_id == target.project_id,
                ImportMappingProfile.entity_type == target.entity_type,
                ImportMappingProfile.name == target.name,
                ImportMappingProfile.active.is_(True),
            )
            .order_by(ImportMappingProfile.version.desc())
            .with_for_update()
        )
    ).scalars().first()
    if latest:
        latest.active = False
        latest.superseded_at = datetime.utcnow()
    next_version = max(target.version, latest.version if latest else 0) + 1
    revision = ImportMappingProfile(
        project_id=target.project_id,
        name=target.name,
        entity_type=target.entity_type,
        configuration=target.configuration,
        version=next_version,
        parent_profile_id=latest.id if latest else target.id,
        active=True,
        created_by=current_principal().username,
    )
    db.add(revision)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="import_mapping_profile",
            entity_id=revision.id,
            action="import_mapping_profile_rolled_back",
            actor=current_principal().username,
            details={
                "project_id": str(target.project_id),
                "restored_profile_id": str(target.id),
                "version": next_version,
            },
        )
    )
    await db.commit()
    await db.refresh(revision)
    return revision


async def _mapped_upload(profile_id: uuid.UUID, uploaded_file: UploadFile, db: AsyncSession):
    profile = await db.get(ImportMappingProfile, profile_id)
    if not profile or not profile.active:
        raise HTTPException(status_code=404, detail="Active import mapping profile not found")
    await _require_project_access(db, profile.project_id, {"approver", "admin"})
    content = await uploaded_file.read(settings.mapped_upload_max_bytes + 1)
    filename = uploaded_file.filename
    await uploaded_file.close()
    try:
        batch = map_import_file(
            filename,
            content,
            entity_type=profile.entity_type,
            configuration=profile.configuration,
            max_bytes=settings.mapped_upload_max_bytes,
            max_records=settings.mapped_import_max_records,
        )
    except MappedIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile, batch, content


def _mapped_job_path(storage_key: str) -> Path:
    if not storage_key or Path(storage_key).name != storage_key:
        raise HTTPException(status_code=500, detail="Import storage key is invalid")
    root = Path(settings.mapped_import_spool_dir).resolve()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=500, detail="Import storage path is invalid")
    return path


@api_router.post(
    "/imports/mapped/jobs",
    response_model=MappedImportJobSummary,
    tags=["Integrations"],
)
async def create_mapped_import_job(
    profile_id: uuid.UUID = Form(...),
    uploaded_file: UploadFile = File(..., alias="file"),
    db: AsyncSession = Depends(get_db),
) -> MappedImportJob:
    require_global_role("approver", "admin")
    profile = await db.get(ImportMappingProfile, profile_id)
    if not profile or not profile.active:
        raise HTTPException(status_code=404, detail="Active import mapping profile not found")
    await _require_project_access(db, profile.project_id, {"approver", "admin"})
    filename = Path(uploaded_file.filename or "").name[:255]
    extension = Path(filename).suffix.lower()
    if extension not in {".json", ".jsonl", ".ndjson", ".csv"}:
        await uploaded_file.close()
        raise HTTPException(status_code=422, detail="Import jobs support JSON, JSONL, NDJSON, and CSV files")
    if profile.configuration.get("record_path"):
        await uploaded_file.close()
        raise HTTPException(status_code=422, detail="Streamed import jobs require top-level source records")
    root = Path(settings.mapped_import_spool_dir).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_key = f"{uuid.uuid4().hex}{extension}"
    final_path = _mapped_job_path(storage_key)
    partial_path = final_path.with_suffix(final_path.suffix + ".partial")
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with partial_path.open("xb") as target:
            while chunk := await uploaded_file.read(1024 * 1024):
                byte_size += len(chunk)
                if byte_size > settings.mapped_job_upload_max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="The uploaded file exceeds the configured streamed-import limit",
                    )
                digest.update(chunk)
                target.write(chunk)
        partial_path.chmod(0o600)
        partial_path.replace(final_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    finally:
        await uploaded_file.close()
    if byte_size == 0:
        final_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    sha256 = digest.hexdigest()
    existing = (
        await db.execute(
            select(MappedImportJob).where(
                MappedImportJob.project_id == profile.project_id,
                MappedImportJob.profile_id == profile.id,
                MappedImportJob.sha256 == sha256,
            )
        )
    ).scalars().first()
    if existing:
        final_path.unlink(missing_ok=True)
        return existing
    job = MappedImportJob(
        project_id=profile.project_id,
        profile_id=profile.id,
        profile_version=profile.version,
        entity_type=profile.entity_type,
        mapping_snapshot=profile.configuration,
        original_filename=filename,
        storage_key=storage_key,
        sha256=sha256,
        byte_size=byte_size,
        status="queued",
        requested_by=current_principal().username,
    )
    db.add(job)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="mapped_import_job",
            entity_id=job.id,
            action="mapped_import_job_queued",
            actor=current_principal().username,
            details={
                "project_id": str(profile.project_id),
                "profile_id": str(profile.id),
                "profile_version": profile.version,
                "filename": filename,
                "sha256": sha256,
                "byte_size": byte_size,
            },
        )
    )
    await db.commit()
    await db.refresh(job)
    return job


@api_router.get(
    "/imports/mapped/jobs",
    response_model=list[MappedImportJobSummary],
    tags=["Integrations"],
)
async def list_mapped_import_jobs(
    project_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[MappedImportJob]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    return list(
        (
            await db.execute(
                select(MappedImportJob)
                .where(MappedImportJob.project_id == project_id)
                .order_by(MappedImportJob.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


@api_router.post(
    "/imports/mapped/jobs/{job_id}/retry",
    response_model=MappedImportJobSummary,
    tags=["Integrations"],
)
async def retry_mapped_import_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MappedImportJob:
    require_global_role("approver", "admin")
    job = await db.get(MappedImportJob, job_id, with_for_update=True)
    if not job:
        raise HTTPException(status_code=404, detail="Mapped import job not found")
    await _require_project_access(db, job.project_id, {"approver", "admin"})
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed import jobs can be retried")
    if not _mapped_job_path(job.storage_key).is_file():
        raise HTTPException(status_code=409, detail="The retained import source is unavailable")
    job.status = "queued"
    job.last_error_type = None
    job.locked_at = None
    job.locked_by = None
    db.add(
        AuditLog(
            entity_type="mapped_import_job",
            entity_id=job.id,
            action="mapped_import_job_retried",
            actor=current_principal().username,
            details={"checkpoint_row": job.checkpoint_row},
        )
    )
    await db.commit()
    await db.refresh(job)
    return job


@api_router.get(
    "/imports/unresolved",
    response_model=list[UnresolvedImportRecordSummary],
    tags=["Integrations"],
)
async def list_unresolved_imports(
    project_id: uuid.UUID,
    status: Literal["pending", "resolved", "dismissed"] = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[UnresolvedImportRecordSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"approver", "admin"})
    result = await db.execute(
        select(UnresolvedImportRecord)
        .where(
            UnresolvedImportRecord.project_id == project_id,
            UnresolvedImportRecord.status == status,
        )
        .order_by(UnresolvedImportRecord.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars())


@api_router.post(
    "/imports/unresolved/{record_id}/retry",
    response_model=UnresolvedImportRecordSummary,
    tags=["Integrations"],
)
async def retry_unresolved_import(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UnresolvedImportRecordSummary:
    require_global_role("approver", "admin")
    record = await db.get(UnresolvedImportRecord, record_id)
    if record is None or record.status != "pending":
        raise HTTPException(status_code=404, detail="Pending unresolved import not found")
    await _require_project_access(db, record.project_id, {"approver", "admin"})
    await resolve_unresolved_records(
        db,
        project_id=record.project_id,
        actor=current_principal().username,
        record_ids={record.id},
    )
    await db.commit()
    await db.refresh(record)
    return record


@api_router.post(
    "/imports/unresolved/{record_id}/dismiss",
    response_model=UnresolvedImportRecordSummary,
    tags=["Integrations"],
)
async def dismiss_unresolved_import(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UnresolvedImportRecordSummary:
    require_global_role("approver", "admin")
    record = await db.get(UnresolvedImportRecord, record_id, with_for_update=True)
    if record is None or record.status != "pending":
        raise HTTPException(status_code=404, detail="Pending unresolved import not found")
    await _require_project_access(db, record.project_id, {"approver", "admin"})
    record.status = "dismissed"
    record.updated_at = datetime.utcnow()
    db.add(
        AuditLog(
            entity_type="unresolved_import",
            entity_id=record.id,
            action="unresolved_import_dismissed",
            actor=current_principal().username,
            details={"missing_reference": record.missing_reference},
        )
    )
    await db.commit()
    await db.refresh(record)
    return record


@api_router.post(
    "/imports/mapped/preview",
    response_model=MappedImportPreview,
    tags=["Integrations"],
)
async def preview_mapped_import(
    profile_id: uuid.UUID = Form(...),
    uploaded_file: UploadFile = File(..., alias="file"),
    db: AsyncSession = Depends(get_db),
) -> MappedImportPreview:
    require_global_role("approver", "admin")
    profile, batch, _ = await _mapped_upload(profile_id, uploaded_file, db)
    issues = list(batch.issues)
    preview_items = list(batch.items)
    skipped = sum(issue.get("severity") == "error" for issue in issues)
    if profile.entity_type == "test_case" and preview_items:
        refs = {item.requirement_external_id for item in preview_items}
        available = set(
            (
                await db.execute(
                    select(Requirement.external_id).where(
                        Requirement.project_id == profile.project_id,
                        Requirement.external_id.in_(refs),
                    )
                )
            ).scalars().all()
        )
        eligible = [item for item in preview_items if item.requirement_external_id in available]
        missing_count = len(preview_items) - len(eligible)
        if missing_count:
            unresolved_policy = profile.configuration.get("options", {}).get(
                "unresolved_reference_policy"
            )
            severity = "warning" if unresolved_policy in {"skip", "stage"} else "error"
            issues.append({
                "severity": severity,
                "message": f"{missing_count} mapped test-case links reference requirements absent from this project",
            })
            skipped += missing_count
        preview_items = eligible
    errors = sum(issue.get("severity") == "error" for issue in issues)
    warnings = sum(issue.get("severity") == "warning" for issue in issues)
    return MappedImportPreview(
        entity_type=profile.entity_type,
        source_record_count=batch.source_record_count,
        mapped_record_count=len(batch.items),
        valid_record_count=len(preview_items),
        skipped_record_count=skipped,
        warning_count=warnings,
        error_count=errors,
        issues=issues[:100],
        samples=[asdict(item) for item in preview_items[:3]],
    )


@api_router.post(
    "/imports/mapped",
    response_model=IntegrationRunSummary,
    tags=["Integrations"],
)
async def execute_mapped_import(
    profile_id: uuid.UUID = Form(...),
    uploaded_file: UploadFile = File(..., alias="file"),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRun:
    require_global_role("approver", "admin")
    profile, batch, content = await _mapped_upload(profile_id, uploaded_file, db)
    blocking = [issue for issue in batch.issues if issue.get("severity") == "error"]
    if blocking:
        raise HTTPException(status_code=422, detail={"message": "Mapped import contains invalid rows", "issues": blocking[:100]})
    actor = current_principal().username
    if profile.entity_type == "test_case":
        items = list(batch.items)
        policy = profile.configuration.get("options", {}).get("unresolved_reference_policy", "reject")
        skipped_missing = 0
        staged_missing = 0
        if policy in {"skip", "stage"}:
            refs = {item.requirement_external_id for item in items}
            available = set(
                (
                    await db.execute(
                        select(Requirement.external_id).where(
                            Requirement.project_id == profile.project_id,
                            Requirement.external_id.in_(refs),
                        )
                    )
                ).scalars().all()
            )
            filtered = [item for item in items if item.requirement_external_id in available]
            missing = [item for item in items if item.requirement_external_id not in available]
            if policy == "stage" and missing:
                staged_missing = await stage_unresolved_test_cases(
                    db,
                    project_id=profile.project_id,
                    profile_id=profile.id,
                    items=missing,
                    actor=actor,
                    existing_record_strategy=profile.configuration.get("options", {}).get(
                        "existing_record_strategy", "new_version"
                    ),
                )
            else:
                skipped_missing = len(missing)
            items = filtered
        if not items:
            if not staged_missing:
                raise HTTPException(status_code=422, detail="No mapped test cases reference requirements in this project")
            run = IntegrationRun(
                integration_type="mapped_test_case_import",
                status="completed",
                requested_by=actor,
                parameters={
                    "project_id": str(profile.project_id),
                    "mapping_profile_id": str(profile.id),
                    "filename": uploaded_file.filename,
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
                result={
                    "source_record_count": batch.source_record_count,
                    "created_test_case_count": 0,
                    "staged_missing_requirement_count": staged_missing,
                    "skipped_missing_requirement_count": skipped_missing,
                },
                completed_at=datetime.utcnow(),
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return run
        try:
            result = await import_historical_test_cases(
                db,
                project_id=profile.project_id,
                items=items,
                actor=actor,
                existing_record_strategy=profile.configuration.get("options", {}).get(
                    "existing_record_strategy", "skip"
                ),
            )
        except HistoricalImportConflictError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        run = await db.get(IntegrationRun, result.run_id)
        run.integration_type = "mapped_test_case_import"
        run.parameters = {**run.parameters, "mapping_profile_id": str(profile.id)}
        run.result = {
            **run.result,
            "source_record_count": batch.source_record_count,
            "mapping_warning_count": len(batch.issues),
            "skipped_missing_requirement_count": skipped_missing,
            "staged_missing_requirement_count": staged_missing,
        }
        await db.commit()
        await db.refresh(run)
        return run

    created_count = 0
    updated_count = 0
    existing_count = 0
    requirement_ids: list[str] = []
    imported_external_ids: set[str] = set()
    for item in batch.items:
        imported_external_ids.add(item.external_id)
        requirement = (
            await db.execute(
                select(Requirement).where(
                    Requirement.project_id == profile.project_id,
                    Requirement.external_id == item.external_id,
                )
            )
        ).scalars().first()
        if requirement:
            strategy = profile.configuration.get("options", {}).get("existing_record_strategy", "skip")
            metadata = item.metadata
            differs = (
                requirement.title != item.title
                or requirement.description != item.description
                or (requirement.metadata_json or {}) != metadata
            )
            if differs and strategy == "reject":
                await db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=f"Requirement {item.external_id} already exists with different content",
                )
            if differs and strategy == "update":
                requirement.title = item.title
                requirement.description = item.description
                requirement.metadata_json = metadata
                requirement.source = "mapped_import"
                requirement.version += 1
                await _snapshot_requirement_and_enqueue(db, requirement)
                updated_count += 1
            else:
                existing_count += 1
        else:
            requirement = Requirement(
                project_id=profile.project_id,
                external_id=item.external_id,
                title=item.title,
                description=item.description,
                source="mapped_import",
                status="draft",
                metadata_json=item.metadata,
            )
            db.add(requirement)
            await db.flush()
            await _snapshot_requirement_and_enqueue(db, requirement)
            created_count += 1
        requirement_ids.append(str(requirement.id))
    resolved_unresolved, still_unresolved = await resolve_unresolved_records(
        db,
        project_id=profile.project_id,
        actor=actor,
        references=imported_external_ids,
    )
    run = IntegrationRun(
        integration_type="mapped_requirement_import",
        status="completed",
        requested_by=actor,
        parameters={
            "project_id": str(profile.project_id),
            "mapping_profile_id": str(profile.id),
            "filename": uploaded_file.filename,
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        result={
            "source_record_count": batch.source_record_count,
            "mapped_count": len(batch.items),
            "created_count": created_count,
            "updated_count": updated_count,
            "existing_count": existing_count,
            "requirement_ids": requirement_ids,
            "mapping_warning_count": len(batch.issues),
            "resolved_unresolved_count": resolved_unresolved,
            "still_unresolved_count": still_unresolved,
        },
        completed_at=datetime.utcnow(),
    )
    db.add(run)
    await db.flush()
    db.add(AuditLog(
        entity_type="integration",
        entity_id=run.id,
        action="mapped_requirements_imported",
        actor=actor,
        details={
            "project_id": str(profile.project_id),
            "profile_id": str(profile.id),
            "created_count": created_count,
            "updated_count": updated_count,
            "existing_count": existing_count,
        },
    ))
    await db.commit()
    await db.refresh(run)
    return run


def _validate_integration_schedule(payload: IntegrationScheduleCreate) -> None:
    if payload.integration_type == "jira":
        jql = str(payload.configuration.get("jql") or "").strip()
        if not jql:
            raise HTTPException(status_code=422, detail="A Jira schedule requires configuration.jql")
        try:
            max_results = int(payload.configuration.get("max_results", 100))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="configuration.max_results must be an integer") from exc
        if not 1 <= max_results <= 1000:
            raise HTTPException(status_code=422, detail="configuration.max_results must be between 1 and 1000")


@api_router.post(
    "/integrations/schedules",
    response_model=IntegrationScheduleSummary,
    tags=["Integrations"],
)
async def create_integration_schedule(
    payload: IntegrationScheduleCreate,
    db: AsyncSession = Depends(get_db),
) -> IntegrationScheduleSummary:
    require_global_role("approver", "admin")
    await _ensure_project(db, payload.project_id)
    await _require_project_access(db, payload.project_id, {"approver", "admin"})
    _validate_integration_schedule(payload)
    schedule = IntegrationSchedule(
        **payload.model_dump(),
        next_run_at=datetime.utcnow() + timedelta(seconds=payload.interval_seconds),
        created_by=current_principal().username,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


@api_router.get(
    "/integrations/schedules",
    response_model=list[IntegrationScheduleSummary],
    tags=["Integrations"],
)
async def list_integration_schedules(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationScheduleSummary]:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"approver", "admin"})
    result = await db.execute(
        select(IntegrationSchedule)
        .where(IntegrationSchedule.project_id == project_id)
        .order_by(IntegrationSchedule.name.asc())
    )
    return list(result.scalars())


@api_router.put(
    "/integrations/schedules/{schedule_id}",
    response_model=IntegrationScheduleSummary,
    tags=["Integrations"],
)
async def update_integration_schedule(
    schedule_id: uuid.UUID,
    payload: IntegrationScheduleCreate,
    db: AsyncSession = Depends(get_db),
) -> IntegrationScheduleSummary:
    require_global_role("approver", "admin")
    schedule = await db.get(IntegrationSchedule, schedule_id, with_for_update=True)
    if schedule is None or schedule.project_id != payload.project_id:
        raise HTTPException(status_code=404, detail="Integration schedule not found")
    await _require_project_access(db, schedule.project_id, {"approver", "admin"})
    _validate_integration_schedule(payload)
    schedule.name = payload.name
    schedule.integration_type = payload.integration_type
    schedule.configuration = payload.configuration
    schedule.interval_seconds = payload.interval_seconds
    schedule.enabled = payload.enabled
    schedule.next_run_at = datetime.utcnow() + timedelta(seconds=payload.interval_seconds)
    schedule.locked_at = None
    schedule.locked_by = None
    await db.commit()
    await db.refresh(schedule)
    return schedule


@api_router.post(
    "/integrations/schedules/{schedule_id}/run",
    response_model=IntegrationScheduleSummary,
    tags=["Integrations"],
)
async def trigger_integration_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> IntegrationScheduleSummary:
    require_global_role("approver", "admin")
    schedule = await db.get(IntegrationSchedule, schedule_id, with_for_update=True)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Integration schedule not found")
    await _require_project_access(db, schedule.project_id, {"approver", "admin"})
    schedule.enabled = True
    schedule.next_run_at = datetime.utcnow()
    schedule.locked_at = None
    schedule.locked_by = None
    await db.commit()
    await db.refresh(schedule)
    return schedule


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
    try:
        return await sync_jira_requirements(
            db,
            project_id=payload.project_id,
            jql=jql,
            max_results=payload.max_results,
            actor=actor,
        )
    except IntegrationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntegrationProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
        DependencyStatusSummary(
            name=probe.name,
            status=probe.status,
            configured=probe.configured,
            detail=probe.detail,
        )
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


@api_router.get(
    "/operations/alerts",
    response_model=list[AlertSummary],
    tags=["Operations"],
)
async def list_alerts(
    project_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AlertSummary]:
    principal = current_principal()
    if principal.role != "admin":
        if project_id is None:
            raise HTTPException(status_code=422, detail="project_id is required")
        await _require_project_access(db, project_id)
    elif project_id is not None:
        await _ensure_project(db, project_id)
    stmt = select(Alert)
    if project_id is not None:
        stmt = stmt.where(Alert.project_id == project_id)
    if status:
        if status not in {"open", "acknowledged"}:
            raise HTTPException(status_code=422, detail="Unsupported alert status")
        stmt = stmt.where(Alert.status == status)
    result = await db.execute(stmt.order_by(Alert.created_at.desc()).limit(limit))
    return result.scalars().all()


@api_router.post(
    "/operations/alerts/{alert_id}/acknowledge",
    response_model=AlertSummary,
    tags=["Operations"],
)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlertSummary:
    alert = await db.get(Alert, alert_id, with_for_update=True)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.project_id is None:
        require_global_role("admin")
    else:
        await _require_project_access(db, alert.project_id, {"approver", "admin"})
    if alert.status != "acknowledged":
        actor = current_principal().username
        alert.status = "acknowledged"
        alert.acknowledged_by = actor
        alert.acknowledged_at = datetime.utcnow()
        db.add(
            AuditLog(
                entity_type="alert",
                entity_id=alert.id,
                action="alert_acknowledged",
                actor=actor,
                details={"category": alert.category, "severity": alert.severity},
            )
        )
        await db.commit()
        await db.refresh(alert)
    return alert


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


@api_router.put(
    "/compliance/projects/{project_id}/profile",
    response_model=ComplianceProfileSummary,
    tags=["Compliance"],
)
async def update_compliance_profile(
    project_id: uuid.UUID,
    payload: ComplianceProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> ComplianceProfileSummary:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"admin"})
    actor = current_principal().username
    normalized_frameworks = sorted({item.strip().upper() for item in payload.frameworks if item.strip()})
    rules = {**payload.model_dump(), "frameworks": normalized_frameworks}
    name = f"compliance-profile:{project_id}"
    policy = await db.scalar(select(GovernancePolicy).where(GovernancePolicy.name == name))
    if policy:
        policy.rules = rules
        policy.status = "active"
        policy.policy_type = "project_compliance"
        policy.updated_at = datetime.utcnow()
    else:
        policy = GovernancePolicy(
            name=name,
            policy_type="project_compliance",
            rules=rules,
            status="active",
            created_by=actor,
        )
        db.add(policy)
        await db.flush()
    db.add(
        AuditLog(
            entity_type="project",
            entity_id=project_id,
            action="compliance_profile_updated",
            actor=actor,
            details={"rules": rules},
        )
    )
    await db.commit()
    await db.refresh(policy)
    profile, _ = await _compliance_profile(db, project_id)
    return profile


@api_router.get(
    "/compliance/projects/{project_id}/profile",
    response_model=ComplianceProfileSummary,
    tags=["Compliance"],
)
async def get_compliance_profile(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ComplianceProfileSummary:
    await _ensure_project(db, project_id)
    await _require_project_access(db, project_id)
    profile, _ = await _compliance_profile(db, project_id)
    return profile


def _pseudonymize_actor(project_id: uuid.UUID, actor: str) -> str:
    digest = hashlib.sha256(f"{project_id}:{actor}".encode("utf-8")).hexdigest()[:16]
    return f"actor-{digest}"


def _pseudonymize_actor_fields(value: object, project_id: uuid.UUID) -> object:
    actor_keys = {"actor", "approved_by", "created_by", "requested_by", "acknowledged_by"}
    if isinstance(value, list):
        return [_pseudonymize_actor_fields(item, project_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _pseudonymize_actor(project_id, item)
            if key in actor_keys and isinstance(item, str)
            else _pseudonymize_actor_fields(item, project_id)
            for key, item in value.items()
        }
    return value


def _as_utc_naive(value: datetime) -> datetime:
    """Normalize API datetimes to the UTC-naive convention used by database columns."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@api_router.get(
    "/compliance/projects/{project_id}/evidence",
    response_model=ComplianceEvidenceExport,
    tags=["Compliance"],
)
async def export_compliance_evidence(
    project_id: uuid.UUID,
    period_start: datetime | None = Query(None),
    period_end: datetime | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
) -> ComplianceEvidenceExport:
    project = await _ensure_project(db, project_id)
    await _require_project_access(db, project_id, {"approver", "admin"})
    profile, _ = await _compliance_profile(db, project_id)
    if not profile.evidence_export_enabled:
        raise HTTPException(status_code=403, detail="Compliance evidence export is disabled for this project")
    end = _as_utc_naive(period_end) if period_end else datetime.utcnow()
    retention_start = end - timedelta(days=profile.evidence_retention_days)
    requested_start = _as_utc_naive(period_start) if period_start else retention_start
    start = max(requested_start, retention_start)
    if start >= end:
        raise HTTPException(status_code=422, detail="period_start must be before period_end")

    requirement_rows = (
        await db.execute(
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.created_at)
            .limit(limit + 1)
        )
    ).scalars().all()
    truncated_sections: set[str] = set()
    if len(requirement_rows) > limit:
        truncated_sections.add("requirements_and_linked_evidence")
    requirements = requirement_rows[:limit]
    requirement_ids = [item.id for item in requirements]
    scenario_rows = (
        await db.execute(select(TestScenario).where(TestScenario.requirement_id.in_(requirement_ids)).limit(limit + 1))
    ).scalars().all() if requirement_ids else []
    test_case_rows = (
        await db.execute(select(TestCase).where(TestCase.requirement_id.in_(requirement_ids)).limit(limit + 1))
    ).scalars().all() if requirement_ids else []
    if len(scenario_rows) > limit or len(test_case_rows) > limit:
        truncated_sections.add("requirements_and_linked_evidence")
    scenarios = scenario_rows[:limit]
    test_cases = test_case_rows[:limit]
    entity_ids = [*requirement_ids, *[item.id for item in scenarios], *[item.id for item in test_cases]]
    approval_rows = (
        await db.execute(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.target_id.in_(entity_ids),
                ApprovalRecord.approved_at >= start,
                ApprovalRecord.approved_at <= end,
            )
            .order_by(ApprovalRecord.approved_at)
            .limit(limit + 1)
        )
    ).scalars().all() if entity_ids else []
    audit_rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_id.in_([project_id, *entity_ids]),
                AuditLog.created_at >= start,
                AuditLog.created_at <= end,
            )
            .order_by(AuditLog.created_at)
            .limit(limit + 1)
        )
    ).scalars().all()
    version_rows = (
        await db.execute(
            select(TestCaseVersion)
            .where(
                TestCaseVersion.requirement_id.in_(requirement_ids),
                TestCaseVersion.approved_at >= start,
                TestCaseVersion.approved_at <= end,
            )
            .order_by(TestCaseVersion.approved_at)
            .limit(limit + 1)
        )
    ).scalars().all() if requirement_ids else []
    calibration_rows = (
        await db.execute(
            select(SemanticCalibrationRun)
            .where(
                SemanticCalibrationRun.project_id == project_id,
                SemanticCalibrationRun.created_at >= start,
                SemanticCalibrationRun.created_at <= end,
            )
            .order_by(SemanticCalibrationRun.created_at)
            .limit(limit + 1)
        )
    ).scalars().all()
    section_rows = {
        "approvals": approval_rows,
        "audit_log": audit_rows,
        "version_history": version_rows,
        "semantic_calibrations": calibration_rows,
    }
    for section, rows in section_rows.items():
        if len(rows) > limit:
            truncated_sections.add(section)
    approvals = approval_rows[:limit]
    audits = audit_rows[:limit]
    versions = version_rows[:limit]
    calibrations = calibration_rows[:limit]

    def exported_actor(value: str) -> str:
        return _pseudonymize_actor(project_id, value) if profile.pseudonymize_actors else value

    def exported_details(value: dict | None) -> object:
        if not profile.pseudonymize_actors:
            return value
        return _pseudonymize_actor_fields(value, project_id)

    evidence = {
        "project": {"id": str(project.id), "name": project.name, "status": project.status},
        "requirements": [
            {"id": str(item.id), "external_id": item.external_id, "title": item.title, "source": item.source, "status": item.status}
            for item in requirements
        ],
        "approvals": [
            {"id": str(item.id), "target_level": item.target_level, "target_id": str(item.target_id), "status": item.status,
             "version": item.version, "notes": item.notes, "actor": exported_actor(item.approved_by), "at": item.approved_at.isoformat()}
            for item in approvals
        ],
        "version_history": [
            {"id": str(item.id), "test_case_id": str(item.test_case_id), "version": item.version, "status": item.status,
             "actor": exported_actor(item.approved_by), "at": item.approved_at.isoformat()}
            for item in versions
        ],
        "audit_log": [
            {"id": str(item.id), "entity_type": item.entity_type, "entity_id": str(item.entity_id) if item.entity_id else None,
             "action": item.action, "actor": exported_actor(item.actor), "details": exported_details(item.details), "at": item.created_at.isoformat()}
            for item in audits
        ],
        "semantic_calibrations": [
            {"id": str(item.id), "dataset_digest": item.dataset_digest, "sample_count": item.sample_count,
             "label_distribution": item.label_distribution, "thresholds": item.proposed_thresholds,
             "metrics": item.metrics, "status": item.status, "actor": exported_actor(item.requested_by), "at": item.created_at.isoformat()}
            for item in calibrations
        ],
    }
    counts = {key: len(value) for key, value in evidence.items() if isinstance(value, list)}
    truncated = sorted(truncated_sections)
    is_complete = not truncated
    generated_at = datetime.utcnow()
    canonical = json.dumps(
        {"evidence": evidence, "record_counts": counts, "is_complete": is_complete, "truncated_sections": truncated},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    db.add(
        AuditLog(
            entity_type="project",
            entity_id=project_id,
            action="compliance_evidence_exported",
            actor=current_principal().username,
            details={"sha256": digest, "period_start": start.isoformat(), "period_end": end.isoformat(), "record_counts": counts},
        )
    )
    await db.commit()
    return ComplianceEvidenceExport(
        project_id=project_id,
        generated_at=generated_at,
        period_start=start,
        period_end=end,
        profile=profile,
        evidence=evidence,
        record_counts=counts,
        is_complete=is_complete,
        truncated_sections=truncated,
        sha256=digest,
    )


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
        source_text = f"Title: {requirement.title}\nDescription: {requirement.description}"
        generation_result = await generation_service.generate(
            requirement_id=str(requirement.id),
            project_id=str(requirement.project_id) if requirement.project_id else None,
            title=requirement.title,
            description=requirement.description,
            external_id=requirement.external_id,
            requirement_version=requirement.version,
            keyword_contexts=await _generation_keyword_contexts(
                db,
                query=source_text,
                project_id=requirement.project_id,
            ),
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
                "retrieval_mode": generation_result.retrieval_mode,
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
