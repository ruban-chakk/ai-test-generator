from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Requirement, UnresolvedImportRecord
from app.services.historical_import import import_historical_test_cases
from app.services.historical_ingestion import ParsedHistoricalStep, ParsedHistoricalTestCase


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _payload(item: ParsedHistoricalTestCase, existing_record_strategy: str) -> dict:
    return {
        "item": jsonable_encoder(asdict(item)),
        "existing_record_strategy": existing_record_strategy,
    }


def _digest(project_id: uuid.UUID, profile_id: uuid.UUID, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{project_id}:{profile_id}:{canonical}".encode()).hexdigest()


async def stage_unresolved_test_cases(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    profile_id: uuid.UUID,
    items: list[ParsedHistoricalTestCase],
    actor: str,
    import_job_id: uuid.UUID | None = None,
    existing_record_strategy: str = "new_version",
) -> int:
    staged = 0
    for item in items:
        payload = _payload(item, existing_record_strategy)
        digest = _digest(project_id, profile_id, payload)
        existing = await db.scalar(
            select(UnresolvedImportRecord).where(UnresolvedImportRecord.dedupe_sha256 == digest)
        )
        if existing:
            if existing.status == "dismissed":
                existing.status = "pending"
                existing.updated_at = _utcnow()
            continue
        db.add(
            UnresolvedImportRecord(
                project_id=project_id,
                profile_id=profile_id,
                import_job_id=import_job_id,
                entity_type="test_case",
                external_id=item.external_id,
                missing_reference=item.requirement_external_id,
                canonical_payload=payload,
                dedupe_sha256=digest,
                created_by=actor,
            )
        )
        staged += 1
    await db.flush()
    return staged


def deserialize_test_case(payload: dict) -> tuple[ParsedHistoricalTestCase, str]:
    raw = payload.get("item") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("Unresolved import payload is invalid")
    raw = dict(raw)
    approved_at = datetime.fromisoformat(str(raw["approved_at"]).replace("Z", "+00:00"))
    raw["approved_at"] = (
        approved_at.astimezone(UTC).replace(tzinfo=None) if approved_at.tzinfo else approved_at
    )
    raw["steps"] = tuple(ParsedHistoricalStep(**step) for step in raw.get("steps", []))
    return ParsedHistoricalTestCase(**raw), str(payload.get("existing_record_strategy") or "new_version")


async def resolve_unresolved_records(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    actor: str,
    references: set[str] | None = None,
    record_ids: set[uuid.UUID] | None = None,
) -> tuple[int, int]:
    statement = (
        select(UnresolvedImportRecord)
        .where(
            UnresolvedImportRecord.project_id == project_id,
            UnresolvedImportRecord.status == "pending",
        )
        .order_by(UnresolvedImportRecord.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    if references:
        statement = statement.where(UnresolvedImportRecord.missing_reference.in_(references))
    if record_ids:
        statement = statement.where(UnresolvedImportRecord.id.in_(record_ids))
    records = list((await db.execute(statement)).scalars())
    if not records:
        return 0, 0
    available = set(
        (
            await db.execute(
                select(Requirement.external_id).where(
                    Requirement.project_id == project_id,
                    Requirement.external_id.in_({record.missing_reference for record in records}),
                )
            )
        ).scalars()
    )
    resolved = failed = 0
    for record in records:
        record.retry_count += 1
        if record.missing_reference not in available:
            record.last_error_type = "MissingRequirement"
            failed += 1
            continue
        try:
            item, strategy = deserialize_test_case(record.canonical_payload)
            async with db.begin_nested():
                await import_historical_test_cases(
                    db,
                    project_id=project_id,
                    items=[item],
                    actor=actor,
                    existing_record_strategy=strategy,
                    record_run=False,
                    commit=False,
                )
        except Exception as exc:
            record.last_error_type = type(exc).__name__[:255]
            failed += 1
            continue
        record.status = "resolved"
        record.last_error_type = None
        record.resolved_at = _utcnow()
        resolved += 1
    await db.flush()
    return resolved, failed
