import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.routes as routes_module
from app.api.routes import approve_test_case, evaluate_quality, get_test_case_approval_workflow
from app.core.config import Settings
from app.core.security import Principal, _principal_context
from app.models import (
    ApprovalRecord,
    ApprovalWorkflowDecision,
    ApprovalWorkflowRun,
    AuditLog,
    GovernancePolicy,
    OutboxEvent,
    Project,
    QualityEvaluation,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestCaseVersion as VersionModel,
    TestScenario as ScenarioModel,
)
from app.schemas import ApprovalAction
from app.services.evaluation import EvaluationResult, JudgeResult


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_test_case_requires_version_bound_evaluation_before_final_approval(monkeypatch) -> None:
    class FakeEvaluationService:
        async def evaluate(self, **_kwargs) -> EvaluationResult:
            return EvaluationResult(
                judgment=JudgeResult.model_validate(
                    {
                        "score": 92,
                        "status": "passed",
                        "scores": {
                            "requirement_coverage": 95,
                            "grounding": 92,
                            "correctness": 94,
                            "completeness": 90,
                            "relevance": 95,
                            "hallucination_rate": 5,
                            "executability": 90,
                            "boundary_and_negative_coverage": 88,
                            "traceability": 95,
                        },
                        "justifications": {
                            "requirement_coverage": "The expected behavior maps to the requirement.",
                            "grounding": "The assertions use supplied requirement facts.",
                            "correctness": "The expected outcome matches the requirement.",
                            "completeness": "The governed approval path is covered.",
                            "relevance": "Every step supports the approval scenario.",
                            "hallucination_rate": "No unsupported behaviors are introduced.",
                            "executability": "The action and result are directly executable.",
                            "boundary_and_negative_coverage": "The governed rejection path is covered.",
                            "traceability": "The case retains requirement and scenario links.",
                        },
                        "issues": [],
                        "summary": "The test case is grounded, executable, and traceable.",
                    }
                ),
                retrieved_context=[],
                model="judge-model",
                rubric_version="test-case-v1",
            )

    environment_settings = Settings(_env_file=None, eval_llm_enabled=False)

    async def effective_settings(_db, _project_id):
        return environment_settings.model_copy(
            update={"eval_llm_enabled": True, "eval_llm_model": "judge-model"}
        ), None

    monkeypatch.setattr(routes_module, "settings", environment_settings)
    monkeypatch.setattr(routes_module, "_effective_ai_settings", effective_settings)
    monkeypatch.setattr(
        routes_module,
        "build_test_case_evaluation_service",
        lambda _config, **_kwargs: FakeEvaluationService(),
    )
    monkeypatch.setattr(routes_module, "_record_ai_usage", lambda *_args, **_kwargs: None)

    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids: dict[str, uuid.UUID] = {}
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="workflow-admin", role="admin", token_version=1)
        )
        try:
            async with sessions() as db:
                project = Project(name=f"workflow-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                ids["project"] = project.id
                db.add(
                    GovernancePolicy(
                        name=f"approval-workflow:{project.id}",
                        status="active",
                        policy_type="approval_workflow",
                        created_by="workflow-admin",
                        rules={
                            "name": "Single governed stage",
                            "version": 1,
                            "stages": [
                                {
                                    "name": "QA approval",
                                    "required_roles": ["admin"],
                                    "minimum_approvals": 1,
                                }
                            ],
                            "evaluation_required": True,
                            "minimum_evaluation_score": 80,
                            "allow_same_approver_multiple_stages": False,
                        },
                    )
                )
                requirement = Requirement(
                    project_id=project.id,
                    external_id="WF-1",
                    title="Approve a generated case",
                    description="A passing evaluation is required before repository eligibility.",
                    source="manual",
                    status="generated",
                )
                db.add(requirement)
                await db.flush()
                ids["requirement"] = requirement.id
                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Governed approval",
                    description="Verify the approval gate.",
                    priority="high",
                    severity="major",
                    category="governance",
                    type="functional",
                )
                db.add(test_scenario)
                await db.flush()
                ids["scenario"] = test_scenario.id
                test_case = CaseModel(
                    requirement_id=requirement.id,
                    scenario_id=test_scenario.id,
                    title="Require passing evaluation",
                    description="Verify approval is blocked until evaluation passes.",
                    priority="high",
                    severity="major",
                    category="governance",
                    type="functional",
                )
                db.add(test_case)
                await db.flush()
                ids["case"] = test_case.id
                db.add(
                    StepModel(
                        test_case_id=test_case.id,
                        step_number=1,
                        action="Request approval before evaluation.",
                        expected_result="The approval request is rejected by policy.",
                    )
                )
                await db.commit()

            async with sessions() as db:
                with pytest.raises(HTTPException) as blocked:
                    await approve_test_case(str(ids["case"]), ApprovalAction(notes="premature"), db)
                assert blocked.value.status_code == 409
                await db.rollback()

            async with sessions() as db:
                evaluation = await evaluate_quality("test_case", str(ids["case"]), db)
                assert evaluation.status == "passed"
                assert evaluation.metrics["evaluation_mode"] == "deterministic_and_llm_judge"
                assert len(evaluation.metrics["deepeval_metrics"]) == 9
                hallucination = next(item for item in evaluation.metrics["deepeval_metrics"] if item["name"] == "hallucination_rate")
                assert hallucination["direction"] == "lower_is_better"
                assert hallucination["normalized_score"] == 95

            async with sessions() as db:
                approved = await approve_test_case(
                    str(ids["case"]),
                    ApprovalAction(notes="reviewed against the requirement"),
                    db,
                )
                assert approved.status == "approved"
                assert approved.repository_status == "pending_index"
                run = await db.scalar(
                    select(ApprovalWorkflowRun).where(ApprovalWorkflowRun.test_case_id == ids["case"])
                )
                assert run is not None
                assert run.status == "approved"
                assert run.quality_evaluation_id is not None
                summary = await get_test_case_approval_workflow(str(ids["case"]), db)
                assert summary is not None
                assert summary.status == "approved"
                assert len(summary.decisions) == 1
        finally:
            _principal_context.reset(token)
            async with sessions() as db:
                run_ids = select(ApprovalWorkflowRun.id).where(ApprovalWorkflowRun.test_case_id == ids.get("case"))
                await db.execute(delete(ApprovalWorkflowDecision).where(ApprovalWorkflowDecision.workflow_run_id.in_(run_ids)))
                await db.execute(delete(ApprovalWorkflowRun).where(ApprovalWorkflowRun.test_case_id == ids.get("case")))
                await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == ids.get("case")))
                await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(
                    select(VersionModel.id).where(VersionModel.test_case_id == ids.get("case"))
                )))
                await db.execute(delete(VersionModel).where(VersionModel.test_case_id == ids.get("case")))
                await db.execute(delete(QualityEvaluation).where(QualityEvaluation.target_id == ids.get("case")))
                await db.execute(delete(ApprovalRecord).where(ApprovalRecord.target_id == ids.get("case")))
                await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_([ids.get("case"), ids.get("project")])))
                await db.execute(delete(StepModel).where(StepModel.test_case_id == ids.get("case")))
                await db.execute(delete(CaseModel).where(CaseModel.id == ids.get("case")))
                await db.execute(delete(ScenarioModel).where(ScenarioModel.id == ids.get("scenario")))
                await db.execute(delete(Requirement).where(Requirement.id == ids.get("requirement")))
                await db.execute(delete(GovernancePolicy).where(GovernancePolicy.name == f"approval-workflow:{ids.get('project')}"))
                await db.execute(delete(Project).where(Project.id == ids.get("project")))
                await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
