from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, settings
from app.models import AuditLog, IntegrationRun, IntegrationSchedule, Requirement
from app.services.integrations import JiraCloudClient
from app.services.outbox import REQUIREMENT_VERSION_INDEX_REQUESTED, enqueue_index_event
from app.services.unresolved_imports import resolve_unresolved_records
from app.services.versioning import snapshot_requirement


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def clean_requirement_text(text: str) -> tuple[str, list[dict]]:
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


async def _snapshot_and_enqueue(db: AsyncSession, requirement: Requirement) -> None:
    version = await snapshot_requirement(db, requirement)
    enqueue_index_event(
        db,
        event_key=f"requirement_version.index:{version.id}",
        event_type=REQUIREMENT_VERSION_INDEX_REQUESTED,
        aggregate_type="requirement_version",
        aggregate_id=version.id,
        payload={"requirement_id": str(requirement.id), "version": requirement.version},
    )


async def sync_jira_requirements(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    jql: str,
    max_results: int,
    actor: str,
    client: JiraCloudClient | None = None,
    schedule_id: uuid.UUID | None = None,
) -> IntegrationRun:
    run = IntegrationRun(
        integration_type="jira_import",
        status="running",
        requested_by=actor,
        parameters={
            "project_id": str(project_id),
            "jql": jql,
            "max_results": max_results,
            "schedule_id": str(schedule_id) if schedule_id else None,
            "mode": "delta_upsert",
        },
        result={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    try:
        issues = await (client or JiraCloudClient()).search_issues(jql, max_results)
    except Exception as exc:
        run.status = "failed"
        run.result = {"error_type": type(exc).__name__}
        run.completed_at = _utcnow()
        await db.commit()
        raise

    imported_ids: list[str] = []
    imported_external_ids: set[str] = set()
    created_count = updated_count = unchanged_count = 0
    for issue in issues:
        requirement = await db.scalar(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.external_id == issue.key,
            )
        )
        cleaned_description, cleanup_issues = clean_requirement_text(issue.description or issue.summary)
        metadata = {
            "jira_issue_type": issue.issue_type,
            "jira_status": issue.status,
            "jira_updated": issue.updated,
            "cleanup_issues": cleanup_issues,
        }
        if requirement:
            changed = (
                requirement.title != issue.summary
                or requirement.description != cleaned_description
                or requirement.metadata_json != metadata
            )
            if changed:
                requirement.version += 1
                requirement.title = issue.summary
                requirement.description = cleaned_description
                requirement.metadata_json = metadata
                requirement.status = "draft"
                await _snapshot_and_enqueue(db, requirement)
                updated_count += 1
            else:
                unchanged_count += 1
        else:
            requirement = Requirement(
                project_id=project_id,
                external_id=issue.key,
                title=issue.summary,
                description=cleaned_description,
                source="jira",
                status="draft",
                metadata_json=metadata,
            )
            db.add(requirement)
            await db.flush()
            await _snapshot_and_enqueue(db, requirement)
            created_count += 1
        imported_ids.append(str(requirement.id))
        imported_external_ids.add(issue.key)

    resolved, still_pending = await resolve_unresolved_records(
        db,
        project_id=project_id,
        actor=actor,
        references=imported_external_ids,
    )
    run.status = "completed"
    run.result = {
        "fetched_count": len(issues),
        "created_count": created_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "resolved_unresolved_count": resolved,
        "still_unresolved_count": still_pending,
        "requirement_ids": imported_ids,
    }
    run.completed_at = _utcnow()
    db.add(
        AuditLog(
            entity_type="integration",
            entity_id=run.id,
            action="jira_import_completed",
            actor=actor,
            details={"project_id": str(project_id), **run.result},
        )
    )
    await db.commit()
    await db.refresh(run)
    return run


class IntegrationScheduleProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: Settings = settings,
        worker_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._worker_id = worker_id or f"integration-schedule-{uuid.uuid4()}"

    async def process_one(self) -> uuid.UUID | None:
        schedule_id = await self._claim()
        if schedule_id is None:
            return None
        status = "completed"
        error_type: str | None = None
        async with self._session_factory() as db:
            schedule = await db.get(IntegrationSchedule, schedule_id)
            if schedule is None:
                return schedule_id
            try:
                await sync_jira_requirements(
                    db,
                    project_id=schedule.project_id,
                    jql=str(schedule.configuration.get("jql") or ""),
                    max_results=int(schedule.configuration.get("max_results") or 100),
                    actor=f"schedule:{schedule.id}",
                    schedule_id=schedule.id,
                )
            except Exception as exc:
                status = "failed"
                error_type = type(exc).__name__[:255]
        async with self._session_factory() as db:
            schedule = await db.get(IntegrationSchedule, schedule_id, with_for_update=True)
            if schedule:
                now = _utcnow()
                schedule.last_run_at = now
                schedule.last_status = status
                schedule.last_error_type = error_type
                schedule.next_run_at = now + timedelta(seconds=schedule.interval_seconds)
                schedule.locked_at = None
                schedule.locked_by = None
                await db.commit()
        return schedule_id

    async def _claim(self) -> uuid.UUID | None:
        stale = _utcnow() - timedelta(seconds=self._config.outbox_lock_timeout_seconds)
        async with self._session_factory() as db:
            schedule = (
                await db.execute(
                    select(IntegrationSchedule)
                    .where(
                        IntegrationSchedule.enabled.is_(True),
                        IntegrationSchedule.next_run_at <= _utcnow(),
                        (IntegrationSchedule.locked_at.is_(None)) | (IntegrationSchedule.locked_at < stale),
                    )
                    .order_by(IntegrationSchedule.next_run_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().first()
            if schedule is None:
                return None
            schedule.locked_at = _utcnow()
            schedule.locked_by = self._worker_id
            await db.commit()
            return schedule.id
