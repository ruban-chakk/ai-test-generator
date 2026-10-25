from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import Text, and_, case, cast, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import Settings, settings
from app.models import Feedback, Requirement, TestCase, TestCaseStep, TestScenario
from app.services.generation import (
    LanguageModel,
    OpenAICompatibleLanguageModel,
    PineconeVectorStore,
    VectorStore,
)


@dataclass(frozen=True)
class SearchMatch:
    vector_id: str
    entity_type: str
    entity_id: str
    title: str
    text: str
    score: float
    metadata: dict[str, Any]
    semantic_score: float | None = None
    keyword_score: float | None = None
    matched_fields: tuple[str, ...] = ()


class SemanticSearchService:
    def __init__(self, language_model: LanguageModel, vector_store: VectorStore) -> None:
        self._language_model = language_model
        self._vector_store = vector_store

    async def search(
        self,
        query: str,
        *,
        project_id: str,
        entity_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
        custom_field: str | None = None,
        custom_value: str | None = None,
        test_case_approval: str = "all",
    ) -> list[SearchMatch]:
        embedding = await self._language_model.embed(query)
        contexts = await self._vector_store.query(
            embedding,
            top_k=min(max((limit + offset) * 4, 20), 400),
            project_id=project_id,
        )
        matches_by_entity: dict[tuple[str, str], SearchMatch] = {}
        for context in contexts:
            metadata = context.metadata
            current_type = str(metadata.get("entity_type") or "")
            current_id = str(metadata.get("entity_id") or metadata.get("requirement_id") or "")
            if not current_type or not current_id or (entity_type and current_type != entity_type):
                continue
            if current_type == "test_case":
                # Dedicated search represents the current test-case record. Immutable
                # approved versions are retained for generation RAG, not shown as a
                # second copy of the same case in search results.
                if metadata.get("immutable_version") is True or metadata.get("artifact_scope") == "approved_version":
                    continue
                status = str(metadata.get("status") or "").lower()
                if test_case_approval == "approved" and status != "approved":
                    continue
                if test_case_approval == "unapproved" and status == "approved":
                    continue
            if custom_field and custom_value is not None:
                safe_key = re.sub(r"[^a-z0-9]+", "_", custom_field.lower()).strip("_")[:80]
                stored = metadata.get(f"custom__{safe_key}")
                values = stored if isinstance(stored, list) else [stored]
                if not any(str(value).lower() == custom_value.lower() for value in values if value is not None):
                    continue
            title = str(metadata.get("title") or metadata.get("external_id") or current_type.replace("_", " ").title())
            key = (current_type, current_id)
            candidate = SearchMatch(
                    vector_id=str(metadata.get("parent_vector_id") or context.id),
                    entity_type=current_type,
                    entity_id=current_id,
                    title=title,
                    text=context.text[:1000],
                    score=context.score,
                    semantic_score=context.score,
                    metadata={
                        key: value
                        for key, value in metadata.items()
                        if key not in {"text", "project_id"}
                    },
                )
            current = matches_by_entity.get(key)
            if current is None or candidate.score > current.score:
                matches_by_entity[key] = candidate
        matches = sorted(matches_by_entity.values(), key=lambda item: (-item.score, item.entity_type, item.entity_id))
        return matches[offset : offset + limit]


def _search_vector(*fields, language: str = settings.search_language):
    empty = literal_column("''")
    separator = literal_column("' '")
    document = func.coalesce(fields[0], empty)
    for field in fields[1:]:
        document = document + separator + func.coalesce(field, empty)
    safe_language = re.sub(r"[^a-zA-Z0-9_]+", "", language) or "simple"
    return func.to_tsvector(literal_column(f"'{safe_language}'::regconfig"), document)


def _query_expression(query: str, aliases: Iterable[str] = (), language: str = settings.search_language):
    terms = [query, *(item for item in aliases if item.strip())]
    expression = " OR ".join(f'"{item.replace(chr(34), " ")}"' for item in terms)
    safe_language = re.sub(r"[^a-zA-Z0-9_]+", "", language) or "simple"
    return func.websearch_to_tsquery(literal_column(f"'{safe_language}'::regconfig"), expression)


def _fuzzy_score(query: str, *fields):
    return func.greatest(
        *(func.word_similarity(query.lower(), func.lower(func.coalesce(field, ""))) for field in fields)
    )


def _escaped_contains(field, query: str):
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return field.ilike(f"%{escaped}%", escape="\\")


def _rank_score(vector, query_expression, *, exact_field=None, title_field=None, query: str):
    score = func.ts_rank_cd(vector, query_expression)
    if title_field is not None:
        score = score + case((_escaped_contains(title_field, query), 1.0), else_=0.0)
    if exact_field is not None:
        score = score + case((func.lower(exact_field) == query.lower(), 4.0), else_=0.0)
    return score


def _normalize_keyword_score(raw_score: float) -> float:
    value = max(0.0, float(raw_score))
    return round(value / (value + 0.5), 4) if value else 0.0


def _matched_fields(query: str, fields: dict[str, str | None]) -> tuple[str, ...]:
    tokens = {token for token in re.findall(r"[a-z0-9_./:-]+", query.lower()) if token}
    phrase = query.lower().strip()
    matched: list[str] = []
    for name, value in fields.items():
        candidate = (value or "").lower()
        if phrase in candidate or (tokens and any(token in candidate for token in tokens)):
            matched.append(name)
    return tuple(matched)


class KeywordSearchService:
    """Project-scoped PostgreSQL full-text search over canonical application records."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def search(
        self,
        query: str,
        *,
        project_id: str,
        entity_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
        aliases: Iterable[str] = (),
        custom_field: str | None = None,
        custom_value: str | None = None,
        test_case_approval: str = "all",
    ) -> list[SearchMatch]:
        candidate_limit = min(max((limit + offset) * 2, 20), 200)
        alias_list = tuple(aliases)
        matches: list[SearchMatch] = []
        if entity_type in {None, "requirement"}:
            matches.extend(await self._requirements(
                query, project_id, candidate_limit, alias_list, custom_field, custom_value
            ))
        if entity_type in {None, "test_case"}:
            matches.extend(await self._test_cases(
                query, project_id, candidate_limit, alias_list, custom_field, custom_value,
                test_case_approval,
            ))
        if entity_type in {None, "feedback"} and not custom_field:
            matches.extend(await self._feedback(query, project_id, candidate_limit, alias_list))
        matches.sort(key=lambda item: (-item.score, item.entity_type, item.entity_id))
        return matches[offset : offset + limit]

    async def _requirements(
        self, query: str, project_id: str, limit: int, aliases: tuple[str, ...],
        custom_field: str | None, custom_value: str | None,
    ) -> list[SearchMatch]:
        custom_fields = cast(Requirement.metadata_json, Text)
        vector = _search_vector(
            Requirement.external_id,
            Requirement.title,
            Requirement.description,
            custom_fields,
        )
        query_expression = _query_expression(query, aliases)
        fuzzy = _fuzzy_score(query, Requirement.external_id, Requirement.title, Requirement.description)
        rank = (_rank_score(
            vector,
            query_expression,
            exact_field=Requirement.external_id,
            title_field=Requirement.title,
            query=query,
        ) + (fuzzy * 0.4)).label("keyword_rank")
        filters = [Requirement.project_id == project_id]
        if custom_field and custom_value is not None:
            filters.append(
                func.lower(
                    func.jsonb_extract_path_text(
                        cast(Requirement.metadata_json, JSONB), "custom_fields", custom_field
                    )
                )
                == custom_value.lower()
            )
        statement = (
            select(Requirement, rank)
            .where(
                *filters,
                or_(
                    vector.op("@@")(query_expression),
                    _escaped_contains(Requirement.external_id, query),
                    _escaped_contains(Requirement.title, query),
                    _escaped_contains(Requirement.description, query),
                    _escaped_contains(custom_fields, query),
                    fuzzy >= 0.35,
                ),
            )
            .order_by(rank.desc(), Requirement.updated_at.desc())
            .limit(limit)
        )
        rows = (await self._db.execute(statement)).all()
        return [
            SearchMatch(
                vector_id=requirement.vector_id or f"requirement:{requirement.id}",
                entity_type="requirement",
                entity_id=str(requirement.id),
                title=requirement.title,
                text=f"Title: {requirement.title}\nDescription: {requirement.description}"[:1000],
                score=_normalize_keyword_score(raw_score),
                keyword_score=_normalize_keyword_score(raw_score),
                matched_fields=_matched_fields(
                    query,
                    {
                        "external ID": requirement.external_id,
                        "title": requirement.title,
                        "description": requirement.description,
                        "custom fields": str((requirement.metadata_json or {}).get("custom_fields", {})),
                    },
                ),
                metadata={
                    "requirement_id": str(requirement.id),
                    "external_id": requirement.external_id or "",
                    "source": requirement.source,
                    "status": requirement.status,
                },
            )
            for requirement, raw_score in rows
        ]

    async def _test_cases(
        self, query: str, project_id: str, limit: int, aliases: tuple[str, ...],
        custom_field: str | None, custom_value: str | None, test_case_approval: str,
    ) -> list[SearchMatch]:
        custom_fields = cast(TestCase.custom_fields_json, Text)
        vector = _search_vector(
            TestCase.title,
            TestCase.description,
            TestCase.prerequisite,
            TestCase.priority,
            TestCase.severity,
            TestCase.category,
            TestCase.type,
            TestScenario.title,
            TestScenario.description,
            custom_fields,
        )
        query_expression = _query_expression(query, aliases)
        fuzzy = _fuzzy_score(
            query,
            TestCase.title,
            TestCase.description,
            TestScenario.title,
            TestScenario.description,
        )
        step_match = (
            select(TestCaseStep.id)
            .where(
                TestCaseStep.test_case_id == TestCase.id,
                or_(
                    _escaped_contains(TestCaseStep.action, query),
                    _escaped_contains(TestCaseStep.expected_result, query),
                ),
            )
            .exists()
        )
        rank = (
            _rank_score(vector, query_expression, title_field=TestCase.title, query=query)
            + case((step_match, 0.75), else_=0.0)
            + (fuzzy * 0.4)
        ).label("keyword_rank")
        filters = [Requirement.project_id == project_id]
        if test_case_approval == "approved":
            filters.append(TestCase.status == "approved")
        elif test_case_approval == "unapproved":
            filters.append(TestCase.status != "approved")
        if custom_field and custom_value is not None:
            filters.append(
                func.lower(
                    func.jsonb_extract_path_text(cast(TestCase.custom_fields_json, JSONB), custom_field)
                ) == custom_value.lower()
            )
        statement = (
            select(TestCase, TestScenario, rank)
            .join(Requirement, Requirement.id == TestCase.requirement_id)
            .join(TestScenario, TestScenario.id == TestCase.scenario_id)
            .options(selectinload(TestCase.steps))
            .where(
                *filters,
                or_(
                    vector.op("@@")(query_expression),
                    _escaped_contains(TestCase.title, query),
                    _escaped_contains(TestCase.description, query),
                    _escaped_contains(TestCase.prerequisite, query),
                    _escaped_contains(TestScenario.title, query),
                    _escaped_contains(TestScenario.description, query),
                    _escaped_contains(custom_fields, query),
                    step_match,
                    fuzzy >= 0.35,
                ),
            )
            .order_by(rank.desc(), TestCase.updated_at.desc())
            .limit(limit)
        )
        rows = (await self._db.execute(statement)).all()
        return [
            SearchMatch(
                vector_id=test_case.vector_id or f"test_case:{test_case.id}:v{test_case.version}",
                entity_type="test_case",
                entity_id=str(test_case.id),
                title=test_case.title,
                text=" ".join(
                    part
                    for part in [
                        test_case.title,
                        test_case.description,
                        test_case.prerequisite,
                        scenario.title,
                        " ".join(
                            f"Step {step.step_number}: {step.action} Expected: {step.expected_result}"
                            for step in sorted(test_case.steps, key=lambda item: item.step_number)
                        ),
                    ]
                    if part
                )[:1000],
                score=_normalize_keyword_score(raw_score),
                keyword_score=_normalize_keyword_score(raw_score),
                matched_fields=_matched_fields(
                    query,
                    {
                        "title": test_case.title,
                        "description": test_case.description,
                        "prerequisite": test_case.prerequisite,
                        "priority": test_case.priority,
                        "severity": test_case.severity,
                        "category": test_case.category,
                        "type": test_case.type,
                        "scenario": f"{scenario.title} {scenario.description}",
                        "steps": " ".join(
                            f"{step.action} {step.expected_result}" for step in test_case.steps
                        ),
                        "custom fields": str(test_case.custom_fields_json or {}),
                    },
                ),
                metadata={
                    "requirement_id": str(test_case.requirement_id),
                    "scenario_id": str(test_case.scenario_id),
                    "status": test_case.status,
                    "repository_status": test_case.repository_status,
                    "version": test_case.version,
                    "priority": test_case.priority or "",
                    "severity": test_case.severity or "",
                    "category": test_case.category or "",
                    "type": test_case.type or "",
                },
            )
            for test_case, scenario, raw_score in rows
        ]

    async def _feedback(
        self, query: str, project_id: str, limit: int, aliases: tuple[str, ...]
    ) -> list[SearchMatch]:
        vector = _search_vector(Feedback.comment, Feedback.feedback_type, Feedback.status)
        query_expression = _query_expression(query, aliases)
        fuzzy = _fuzzy_score(query, Feedback.comment, Feedback.feedback_type)
        rank = (_rank_score(vector, query_expression, query=query) + (fuzzy * 0.4)).label("keyword_rank")
        project_requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
        project_scenario_ids = (
            select(TestScenario.id)
            .join(Requirement, Requirement.id == TestScenario.requirement_id)
            .where(Requirement.project_id == project_id)
        )
        project_test_case_ids = (
            select(TestCase.id)
            .join(Requirement, Requirement.id == TestCase.requirement_id)
            .where(Requirement.project_id == project_id)
        )
        statement = (
            select(Feedback, rank)
            .where(
                or_(
                    and_(Feedback.target_level == "requirement", Feedback.target_id.in_(project_requirement_ids)),
                    and_(Feedback.target_level == "scenario", Feedback.target_id.in_(project_scenario_ids)),
                    and_(Feedback.target_level == "test_case", Feedback.target_id.in_(project_test_case_ids)),
                ),
                or_(
                    vector.op("@@")(query_expression),
                    _escaped_contains(Feedback.comment, query),
                    _escaped_contains(Feedback.feedback_type, query),
                    fuzzy >= 0.35,
                ),
            )
            .order_by(rank.desc(), Feedback.created_at.desc())
            .limit(limit)
        )
        rows = (await self._db.execute(statement)).all()
        scenario_targets = {
            feedback.target_id for feedback, _ in rows if feedback.target_level == "scenario"
        }
        test_case_targets = {
            feedback.target_id for feedback, _ in rows if feedback.target_level == "test_case"
        }
        scenario_requirements = dict(
            (
                await self._db.execute(
                    select(TestScenario.id, TestScenario.requirement_id).where(
                        TestScenario.id.in_(scenario_targets)
                    )
                )
            ).all()
        ) if scenario_targets else {}
        test_case_requirements = dict(
            (
                await self._db.execute(
                    select(TestCase.id, TestCase.requirement_id).where(TestCase.id.in_(test_case_targets))
                )
            ).all()
        ) if test_case_targets else {}
        matches: list[SearchMatch] = []
        for feedback, raw_score in rows:
            if feedback.target_level == "requirement":
                requirement_id = feedback.target_id
            elif feedback.target_level == "scenario":
                requirement_id = scenario_requirements.get(feedback.target_id)
            elif feedback.target_level == "test_case":
                requirement_id = test_case_requirements.get(feedback.target_id)
            else:
                requirement_id = None
            matches.append(
                SearchMatch(
                    vector_id=feedback.vector_id or f"feedback:{feedback.id}",
                    entity_type="feedback",
                    entity_id=str(feedback.id),
                    title=f"{feedback.feedback_type.replace('_', ' ').title()} feedback",
                    text=feedback.comment[:1000],
                    score=_normalize_keyword_score(raw_score),
                    keyword_score=_normalize_keyword_score(raw_score),
                    matched_fields=_matched_fields(
                        query,
                        {
                            "comment": feedback.comment,
                            "feedback type": feedback.feedback_type,
                            "status": feedback.status,
                        },
                    ),
                    metadata={
                        "target_level": feedback.target_level,
                        "target_id": str(feedback.target_id),
                        "feedback_type": feedback.feedback_type,
                        "status": feedback.status,
                        **({"requirement_id": str(requirement_id)} if requirement_id else {}),
                    },
                )
            )
        return matches


def fuse_search_matches(
    semantic_matches: Iterable[SearchMatch],
    keyword_matches: Iterable[SearchMatch],
    *,
    limit: int,
    rank_constant: int = 60,
) -> list[SearchMatch]:
    """Merge incomparable provider scores with reciprocal-rank fusion."""

    semantic = list(semantic_matches)
    keyword = list(keyword_matches)
    by_key: dict[tuple[str, str], dict[str, SearchMatch]] = {}
    fused_scores: dict[tuple[str, str], float] = {}
    for source, matches in (("semantic", semantic), ("keyword", keyword)):
        for rank, match in enumerate(matches, start=1):
            key = (match.entity_type, match.entity_id)
            by_key.setdefault(key, {})[source] = match
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (rank_constant + rank)

    maximum = 2.0 / (rank_constant + 1)
    results: list[SearchMatch] = []
    for key, sources in by_key.items():
        semantic_match = sources.get("semantic")
        keyword_match = sources.get("keyword")
        base = keyword_match or semantic_match
        assert base is not None
        metadata = {
            **(semantic_match.metadata if semantic_match else {}),
            **(keyword_match.metadata if keyword_match else {}),
        }
        selected = semantic_match or keyword_match
        assert selected is not None
        results.append(
            SearchMatch(
                vector_id=selected.vector_id,
                entity_type=base.entity_type,
                entity_id=base.entity_id,
                title=base.title,
                text=base.text,
                score=round(min(1.0, fused_scores[key] / maximum), 4),
                semantic_score=semantic_match.score if semantic_match else None,
                keyword_score=keyword_match.score if keyword_match else None,
                matched_fields=keyword_match.matched_fields if keyword_match else (),
                metadata=metadata,
            )
        )
    results.sort(
        key=lambda item: (
            -item.score,
            -(item.semantic_score or 0.0),
            -(item.keyword_score or 0.0),
            item.entity_type,
            item.entity_id,
        )
    )
    return results[:limit]


def build_semantic_search_service(config: Settings = settings) -> SemanticSearchService:
    return SemanticSearchService(
        OpenAICompatibleLanguageModel(config),
        PineconeVectorStore(config),
    )
