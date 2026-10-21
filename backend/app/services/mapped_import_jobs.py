from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, settings
from app.models import (
    AuditLog,
    IntegrationRun,
    MappedImportJob,
    Requirement,
)
from app.services.file_ingestion import ParsedRequirement
from app.services.historical_import import import_historical_test_cases
from app.services.historical_ingestion import ParsedHistoricalTestCase
from app.services.mapped_ingestion import MappedIngestionError, iter_source_records, map_import_records
from app.services.outbox import REQUIREMENT_VERSION_INDEX_REQUESTED, enqueue_index_event
from app.services.unresolved_imports import resolve_unresolved_records, stage_unresolved_test_cases
from app.services.versioning import snapshot_requirement


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class PersistedBatch:
    created: int = 0
    updated: int = 0
    existing: int = 0
    skipped: int = 0
    unresolved: int = 0


class MappedImportJobProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: Settings = settings,
        worker_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._worker_id = worker_id or f"mapped-import-{uuid.uuid4()}"

    async def process_batch(self) -> uuid.UUID | None:
        job_id = await self._claim()
        if job_id is None:
            return None
        remove_path: Path | None = None
        try:
            async with self._session_factory() as db:
                job = await db.get(MappedImportJob, job_id, with_for_update=True)
                if not job or job.status != "processing" or job.locked_by != self._worker_id:
                    return job_id
                path = self._job_path(job)
                records, has_more = self._read_batch(job, path)
                if not records:
                    await self._complete_job(db, job)
                    await db.commit()
                    remove_path = path
                else:
                    batch = map_import_records(
                        records,
                        entity_type=job.entity_type,
                        configuration=job.mapping_snapshot,
                        filename=job.original_filename,
                        digest=job.sha256,
                        start_row=job.checkpoint_row + 1,
                        max_records=self._config.mapped_job_batch_size,
                    )
                    errors = [issue for issue in batch.issues if issue.get("severity") == "error"]
                    if errors:
                        raise MappedIngestionError(f"Mapped batch contains {len(errors)} invalid source records")
                    persisted = await self._persist_batch(db, job, batch.items)
                    job.checkpoint_row += batch.source_record_count
                    job.source_record_count += batch.source_record_count
                    job.mapped_record_count += len(batch.items)
                    job.created_record_count += persisted.created
                    job.updated_record_count += persisted.updated
                    job.existing_record_count += persisted.existing
                    job.skipped_record_count += persisted.skipped
                    job.unresolved_record_count += persisted.unresolved
                    job.warning_count += sum(
                        issue.get("severity") == "warning" for issue in batch.issues
                    )
                    job.last_error_type = None
                    job.locked_at = None
                    job.locked_by = None
                    if has_more:
                        job.status = "queued"
                    else:
                        await self._complete_job(db, job)
                        remove_path = path
                    await db.commit()
        except Exception as exc:
            await self._fail(job_id, type(exc).__name__)
            return job_id
        if remove_path is not None:
            remove_path.unlink(missing_ok=True)
        return job_id

    async def _claim(self) -> uuid.UUID | None:
        stale_before = _utcnow() - timedelta(seconds=self._config.outbox_lock_timeout_seconds)
        async with self._session_factory() as db:
            job = (
                await db.execute(
                    select(MappedImportJob)
                    .where(
                        (MappedImportJob.status == "queued")
                        | (
                            (MappedImportJob.status == "processing")
                            & (MappedImportJob.locked_at < stale_before)
                        )
                    )
                    .order_by(MappedImportJob.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().first()
            if not job:
                return None
            job.status = "processing"
            job.locked_at = _utcnow()
            job.locked_by = self._worker_id
            await db.commit()
            return job.id

    def _job_path(self, job: MappedImportJob) -> Path:
        if not job.storage_key or Path(job.storage_key).name != job.storage_key:
            raise MappedIngestionError("Import job storage key is invalid")
        root = Path(self._config.mapped_import_spool_dir).resolve()
        path = (root / job.storage_key).resolve()
        if root not in path.parents:
            raise MappedIngestionError("Import job storage path is invalid")
        if not path.is_file():
            raise FileNotFoundError("Import job source file is unavailable")
        return path

    def _read_batch(self, job: MappedImportJob, path: Path) -> tuple[list[dict], bool]:
        extension = Path(job.original_filename).suffix.lower()
        if job.mapping_snapshot.get("record_path"):
            raise MappedIngestionError("Resumable streamed imports require top-level records")
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            iterator = iter_source_records(stream, extension)
            for _ in itertools.islice(iterator, job.checkpoint_row):
                pass
            values = list(itertools.islice(iterator, self._config.mapped_job_batch_size + 1))
        if job.checkpoint_row + min(len(values), self._config.mapped_job_batch_size) > self._config.mapped_job_max_records:
            raise MappedIngestionError("The import exceeds the configured mapped-job record limit")
        return values[: self._config.mapped_job_batch_size], len(values) > self._config.mapped_job_batch_size

    async def _persist_batch(
        self,
        db: AsyncSession,
        job: MappedImportJob,
        items: tuple[ParsedRequirement | ParsedHistoricalTestCase, ...],
    ) -> PersistedBatch:
        if job.entity_type == "requirement":
            return await self._persist_requirements(db, job, items)
        test_cases = [item for item in items if isinstance(item, ParsedHistoricalTestCase)]
        policy = job.mapping_snapshot.get("options", {}).get("unresolved_reference_policy", "reject")
        skipped = unresolved = 0
        if policy in {"skip", "stage"}:
            refs = {item.requirement_external_id for item in test_cases}
            available = set(
                (
                    await db.execute(
                        select(Requirement.external_id).where(
                            Requirement.project_id == job.project_id,
                            Requirement.external_id.in_(refs),
                        )
                    )
                ).scalars().all()
            )
            filtered = [item for item in test_cases if item.requirement_external_id in available]
            missing = [item for item in test_cases if item.requirement_external_id not in available]
            if policy == "stage" and missing:
                unresolved = await stage_unresolved_test_cases(
                    db,
                    project_id=job.project_id,
                    profile_id=job.profile_id,
                    import_job_id=job.id,
                    items=missing,
                    actor=job.requested_by,
                    existing_record_strategy=job.mapping_snapshot.get("options", {}).get(
                        "existing_record_strategy", "new_version"
                    ),
                )
            else:
                skipped = len(missing)
            test_cases = filtered
        if not test_cases:
            return PersistedBatch(skipped=skipped, unresolved=unresolved)
        result = await import_historical_test_cases(
            db,
            project_id=job.project_id,
            items=test_cases,
            actor=job.requested_by,
            existing_record_strategy=job.mapping_snapshot.get("options", {}).get(
                "existing_record_strategy", "skip"
            ),
            record_run=False,
            commit=False,
        )
        return PersistedBatch(
            created=result.created_test_case_count,
            updated=result.updated_test_case_count,
            existing=result.existing_test_case_count,
            skipped=skipped,
            unresolved=unresolved,
        )

    async def _persist_requirements(
        self,
        db: AsyncSession,
        job: MappedImportJob,
        items: tuple[ParsedRequirement | ParsedHistoricalTestCase, ...],
    ) -> PersistedBatch:
        created = updated = existing = 0
        strategy = job.mapping_snapshot.get("options", {}).get("existing_record_strategy", "skip")
        imported_references: set[str] = set()
        for item in items:
            if not isinstance(item, ParsedRequirement):
                continue
            imported_references.add(item.external_id)
            requirement = (
                await db.execute(
                    select(Requirement)
                    .where(
                        Requirement.project_id == job.project_id,
                        Requirement.external_id == item.external_id,
                    )
                    .with_for_update()
                )
            ).scalars().first()
            if requirement is None:
                requirement = Requirement(
                    project_id=job.project_id,
                    external_id=item.external_id,
                    title=item.title,
                    description=item.description,
                    source="mapped_import",
                    status="draft",
                    metadata_json=item.metadata,
                )
                db.add(requirement)
                await db.flush()
                await self._snapshot_and_enqueue(db, requirement)
                created += 1
                continue
            differs = (
                requirement.title != item.title
                or requirement.description != item.description
                or (requirement.metadata_json or {}) != item.metadata
            )
            if differs and strategy == "reject":
                raise MappedIngestionError(
                    f"Requirement {item.external_id} already exists with different content"
                )
            if differs and strategy == "update":
                requirement.title = item.title
                requirement.description = item.description
                requirement.metadata_json = item.metadata
                requirement.source = "mapped_import"
                requirement.version += 1
                await self._snapshot_and_enqueue(db, requirement)
                updated += 1
            else:
                existing += 1
        if imported_references:
            resolved, failed = await resolve_unresolved_records(
                db,
                project_id=job.project_id,
                actor=job.requested_by,
                references=imported_references,
            )
            if resolved or failed:
                db.add(
                    AuditLog(
                        entity_type="mapped_import_job",
                        entity_id=job.id,
                        action="unresolved_imports_reconciled",
                        actor=job.requested_by,
                        details={"resolved": resolved, "still_pending": failed},
                    )
                )
        return PersistedBatch(created=created, updated=updated, existing=existing)

    async def _snapshot_and_enqueue(self, db: AsyncSession, requirement: Requirement) -> None:
        version = await snapshot_requirement(db, requirement)
        enqueue_index_event(
            db,
            event_key=f"requirement_version.index:{version.id}",
            event_type=REQUIREMENT_VERSION_INDEX_REQUESTED,
            aggregate_type="requirement_version",
            aggregate_id=version.id,
            payload={"requirement_id": str(requirement.id), "version": requirement.version},
        )

    async def _complete_job(self, db: AsyncSession, job: MappedImportJob) -> None:
        job.status = "completed"
        job.completed_at = _utcnow()
        job.locked_at = None
        job.locked_by = None
        job.result = {
            "source_record_count": job.source_record_count,
            "mapped_record_count": job.mapped_record_count,
            "created_record_count": job.created_record_count,
            "updated_record_count": job.updated_record_count,
            "existing_record_count": job.existing_record_count,
            "skipped_record_count": job.skipped_record_count,
            "unresolved_record_count": job.unresolved_record_count,
            "warning_count": job.warning_count,
        }
        run = IntegrationRun(
            integration_type=f"streamed_mapped_{job.entity_type}_import",
            status="completed",
            requested_by=job.requested_by,
            parameters={
                "project_id": str(job.project_id),
                "mapping_profile_id": str(job.profile_id),
                "mapping_profile_version": job.profile_version,
                "filename": job.original_filename,
                "sha256": job.sha256,
                "import_job_id": str(job.id),
            },
            result=job.result,
            completed_at=job.completed_at,
        )
        db.add(run)
        await db.flush()
        db.add(
            AuditLog(
                entity_type="mapped_import_job",
                entity_id=job.id,
                action="mapped_import_job_completed",
                actor=job.requested_by,
                details={"integration_run_id": str(run.id), **job.result},
            )
        )

    async def _fail(self, job_id: uuid.UUID, error_type: str) -> None:
        async with self._session_factory() as db:
            job = await db.get(MappedImportJob, job_id, with_for_update=True)
            if not job:
                return
            job.status = "failed"
            job.error_count += 1
            job.last_error_type = error_type[:255]
            job.locked_at = None
            job.locked_by = None
            await db.commit()
