import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    requirements = relationship("Requirement", back_populates="project")
    memberships = relationship("ProjectMembership", back_populates="project", cascade="all, delete-orphan")


class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    external_id = Column(String, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    metadata_json = Column("metadata", JSON, key="metadata_json", nullable=True)
    vector_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="requirements")
    scenarios = relationship("TestScenario", back_populates="requirement", cascade="all, delete")
    test_cases = relationship("TestCase", back_populates="requirement", cascade="all, delete")


class TestScenario(Base):
    __tablename__ = "test_scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    category = Column(String, nullable=True)
    type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    vector_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    requirement = relationship("Requirement", back_populates="scenarios")
    test_cases = relationship("TestCase", back_populates="scenario", cascade="all, delete")


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("test_scenarios.id", ondelete="CASCADE"), nullable=False)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    prerequisite = Column(Text, nullable=True)
    priority = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    category = Column(String, nullable=True)
    type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    approved_at = Column(DateTime, nullable=True)
    locked = Column(Boolean, nullable=False, default=False)
    repository_status = Column(String, nullable=False, default="draft")
    repository_synced_at = Column(DateTime, nullable=True)
    vector_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    scenario = relationship("TestScenario", back_populates="test_cases")
    requirement = relationship("Requirement", back_populates="test_cases")
    steps = relationship("TestCaseStep", back_populates="test_case", cascade="all, delete")
    versions = relationship("TestCaseVersion", back_populates="test_case", cascade="all, delete")
    execution_runs = relationship("TestExecutionRun", back_populates="test_case", cascade="all, delete")


class TestCaseStep(Base):
    __tablename__ = "test_case_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id = Column(UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    action = Column(Text, nullable=False)
    expected_result = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    test_case = relationship("TestCase", back_populates="steps")


class TestCaseVersion(Base):
    __tablename__ = "test_case_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id = Column(UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("test_scenarios.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    prerequisite = Column(Text, nullable=True)
    priority = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    category = Column(String, nullable=True)
    type = Column(String, nullable=True)
    status = Column(String, nullable=False)
    approved_by = Column(String, nullable=False)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(Text, nullable=True)
    steps_snapshot = Column(JSON, nullable=False, default=list)

    test_case = relationship("TestCase", back_populates="versions")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_level = Column(String, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    source = Column(String, nullable=False)
    feedback_type = Column(String, nullable=False)
    comment = Column(Text, nullable=False)
    created_by = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    vector_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RevisionRecord(Base):
    __tablename__ = "revision_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id = Column(UUID(as_uuid=True), ForeignKey("feedback.id", ondelete="SET NULL"), nullable=True)
    target_level = Column(String, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String, nullable=False)
    status = Column(String, nullable=False, default="completed")
    created_by = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    source_snapshot = Column(JSON, nullable=True)
    result_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class QualityEvaluation(Base):
    __tablename__ = "quality_evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_level = Column(String, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    score = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    metrics = Column(JSON, nullable=False, default=dict)
    issues = Column(JSON, nullable=False, default=list)
    evaluated_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ImpactAnalysis(Base):
    __tablename__ = "impact_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True)
    source_text = Column(Text, nullable=False)
    similarity_threshold = Column(Integer, nullable=False, default=80)
    duplicates = Column(JSON, nullable=False, default=list)
    deprecations = Column(JSON, nullable=False, default=list)
    updates = Column(JSON, nullable=False, default=list)
    risk_score = Column(Integer, nullable=False, default=0)
    coverage_score = Column(Integer, nullable=False, default=0)
    summary = Column(JSON, nullable=False, default=dict)
    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class IntegrationRun(Base):
    __tablename__ = "integration_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="completed")
    requested_by = Column(String, nullable=False, default="system")
    parameters = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class RepositorySyncRun(Base):
    __tablename__ = "repository_sync_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository = Column(String, nullable=False)
    branch = Column(String, nullable=False, default="main")
    status = Column(String, nullable=False, default="completed")
    synced_count = Column(Integer, nullable=False, default=0)
    vector_synced_count = Column(Integer, nullable=False, default=0)
    requested_by = Column(String, nullable=False, default="system")
    details = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite = Column(String, nullable=False)
    status = Column(String, nullable=False)
    score = Column(Integer, nullable=False, default=0)
    metrics = Column(JSON, nullable=False, default=dict)
    issues = Column(JSON, nullable=False, default=list)
    requested_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class OperationalMetric(Base):
    __tablename__ = "operational_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Integer, nullable=False)
    dimensions = Column(JSON, nullable=False, default=dict)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class GovernancePolicy(Base):
    __tablename__ = "governance_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="active")
    policy_type = Column(String, nullable=False)
    rules = Column(JSON, nullable=False, default=dict)
    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TestExecutionRun(Base):
    __tablename__ = "test_execution_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    test_case_id = Column(
        UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_version = Column(Integer, nullable=False)
    environment = Column(String, nullable=False, default="default")
    runner = Column(String, nullable=False, default="generic")
    status = Column(String, nullable=False, default="queued", index=True)
    idempotency_key = Column(String, nullable=False, unique=True)
    external_run_id = Column(String, nullable=True)
    result = Column(JSON, nullable=False, default=dict)
    requested_by = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    test_case = relationship("TestCase", back_populates="execution_runs")


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_level = Column(String, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    approved_by = Column(String, nullable=False)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=False, unique=True)
    role = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project_memberships = relationship("ProjectMembership", back_populates="user", cascade="all, delete-orphan")


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_membership"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False, default="reviewer")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="memberships")
    user = relationship("User", back_populates="project_memberships")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_key = Column(String, nullable=False, unique=True)
    event_type = Column(String, nullable=False, index=True)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
