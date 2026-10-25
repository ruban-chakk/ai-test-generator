import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()
DEFAULT_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_project_organization_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True, default=lambda: DEFAULT_ORGANIZATION_ID)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    cost_center = Column(String(128), nullable=False, default="unassigned")
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    requirements = relationship("Requirement", back_populates="project")
    organization = relationship("Organization", back_populates="projects")
    memberships = relationship("ProjectMembership", back_populates="project", cascade="all, delete-orphan")
    import_mapping_profiles = relationship(
        "ImportMappingProfile", back_populates="project", cascade="all, delete-orphan"
    )
    knowledge_documents = relationship(
        "KnowledgeDocument", back_populates="project", cascade="all, delete-orphan"
    )


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(128), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    projects = relationship("Project", back_populates="organization")
    memberships = relationship("OrganizationMembership", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_organization_membership"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="member")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="organization_memberships")


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    email = Column(String(320), nullable=False, index=True)
    organization_role = Column(String(32), nullable=False, default="member")
    project_role = Column(String(64), nullable=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AIModelConfiguration(Base):
    __tablename__ = "ai_model_configurations"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", name="uq_ai_model_configuration_scope"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type = Column(String(16), nullable=False, index=True)
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    generation_model = Column(String(255), nullable=False)
    judge_model = Column(String(255), nullable=False)
    embedding_model = Column(String(255), nullable=False)
    vector_provider = Column(String(64), nullable=False, default="pinecone")
    vector_index = Column(String(255), nullable=False)
    vector_namespace = Column(String(255), nullable=False)
    vector_host = Column(String(500), nullable=True)
    credential_reference = Column(String(255), nullable=True)
    evaluation_weights = Column(JSON, nullable=False, default=dict)
    pricing = Column(JSON, nullable=False, default=dict)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PromptConfiguration(Base):
    """Scoped, versioned business prompt templates."""

    __tablename__ = "prompt_configurations"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", "prompt_key", name="uq_prompt_configuration_scope_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type = Column(String(16), nullable=False, index=True)
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    prompt_key = Column(String(64), nullable=False, index=True)
    system_template = Column(Text, nullable=False)
    user_template = Column(Text, nullable=False)
    variables = Column(JSON, nullable=False, default=list)
    temperature = Column(Float, nullable=True)
    change_notes = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="published", index=True)
    content_checksum = Column(String(64), nullable=False, default="")
    parent_configuration_id = Column(UUID(as_uuid=True), ForeignKey("prompt_configurations.id", ondelete="SET NULL"), nullable=True)
    parent_version = Column(Integer, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PromptConfigurationVersion(Base):
    """Immutable prompt snapshot used for history, rollback, and reproducibility."""

    __tablename__ = "prompt_configuration_versions"
    __table_args__ = (
        UniqueConstraint("prompt_configuration_id", "version", name="uq_prompt_configuration_version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_configuration_id = Column(UUID(as_uuid=True), ForeignKey("prompt_configurations.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt_key = Column(String(64), nullable=False, index=True)
    scope_type = Column(String(16), nullable=False, index=True)
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    version = Column(Integer, nullable=False)
    system_template = Column(Text, nullable=False)
    user_template = Column(Text, nullable=False)
    variables = Column(JSON, nullable=False, default=list)
    temperature = Column(Float, nullable=True)
    change_notes = Column(Text, nullable=True)
    status = Column(String(16), nullable=False)
    content_checksum = Column(String(64), nullable=False)
    parent_configuration_id = Column(UUID(as_uuid=True), nullable=True)
    parent_version = Column(Integer, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AIUsageRecord(Base):
    __tablename__ = "ai_usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    operation = Column(String(64), nullable=False, index=True)
    model = Column(String(255), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_micros = Column(BigInteger, nullable=False, default=0)
    input_rate_per_million = Column(Float, nullable=False, default=0)
    output_rate_per_million = Column(Float, nullable=False, default=0)
    pricing_source = Column(String(64), nullable=False, default="unpriced")
    metadata_json = Column("metadata", JSON, key="metadata_json", nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ImportMappingProfile(Base):
    __tablename__ = "import_mapping_profiles"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "entity_type", "name", "version", name="uq_import_mapping_profile_name_version"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    entity_type = Column(String(32), nullable=False, index=True)
    configuration = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    parent_profile_id = Column(
        UUID(as_uuid=True), ForeignKey("import_mapping_profiles.id", ondelete="SET NULL"), nullable=True
    )
    active = Column(Boolean, nullable=False, default=True)
    superseded_at = Column(DateTime, nullable=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="import_mapping_profiles")


class VectorChunk(Base):
    """Durable inventory of vectors emitted for one outbox aggregate."""

    __tablename__ = "vector_chunks"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_type", "aggregate_id", "chunk_index", name="uq_vector_chunk_aggregate_index"
        ),
        UniqueConstraint("vector_id", name="uq_vector_chunk_vector_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    aggregate_type = Column(String(64), nullable=False, index=True)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entity_type = Column(String(32), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    vector_id = Column(String(512), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_count = Column(Integer, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    indexed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MappedImportJob(Base):
    __tablename__ = "mapped_import_jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "profile_id", "sha256", name="uq_mapped_import_job_source"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("import_mapping_profiles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile_version = Column(Integer, nullable=False)
    entity_type = Column(String(32), nullable=False, index=True)
    mapping_snapshot = Column(JSON, nullable=False)
    original_filename = Column(String(255), nullable=False)
    storage_key = Column(String(64), nullable=False, unique=True)
    sha256 = Column(String(64), nullable=False)
    byte_size = Column(BigInteger, nullable=False)
    status = Column(String(32), nullable=False, default="queued", index=True)
    checkpoint_row = Column(Integer, nullable=False, default=0)
    source_record_count = Column(Integer, nullable=False, default=0)
    mapped_record_count = Column(Integer, nullable=False, default=0)
    created_record_count = Column(Integer, nullable=False, default=0)
    updated_record_count = Column(Integer, nullable=False, default=0)
    existing_record_count = Column(Integer, nullable=False, default=0)
    skipped_record_count = Column(Integer, nullable=False, default=0)
    unresolved_record_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    result = Column(JSON, nullable=False, default=dict)
    last_error_type = Column(String(255), nullable=True)
    requested_by = Column(String(255), nullable=False)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class BulkOperationJob(Base):
    """Durable queue entry for multi-requirement generation/impact work."""

    __tablename__ = "bulk_operation_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    requirement_ids = Column(JSON, nullable=False, default=list)
    total_count = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    result = Column(JSON, nullable=False, default=dict)
    last_error_type = Column(String(255), nullable=True)
    requested_by = Column(String(255), nullable=False)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class UnresolvedImportRecord(Base):
    __tablename__ = "unresolved_import_records"
    __table_args__ = (UniqueConstraint("dedupe_sha256", name="uq_unresolved_import_dedupe"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("import_mapping_profiles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    import_job_id = Column(
        UUID(as_uuid=True), ForeignKey("mapped_import_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity_type = Column(String(32), nullable=False, default="test_case")
    external_id = Column(String(255), nullable=False)
    missing_reference = Column(String(255), nullable=False, index=True)
    canonical_payload = Column(JSON, nullable=False)
    dedupe_sha256 = Column(String(64), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    last_error_type = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    external_id = Column(String, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    metadata_json = Column("metadata", JSON, key="metadata_json", nullable=True)
    vector_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="requirements")
    scenarios = relationship("TestScenario", back_populates="requirement", cascade="all, delete")
    test_cases = relationship("TestCase", back_populates="requirement", cascade="all, delete")
    versions = relationship("RequirementVersion", back_populates="requirement", cascade="all, delete")


class RequirementVersion(Base):
    __tablename__ = "requirement_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, nullable=False)
    external_id = Column(String, nullable=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    status = Column(String, nullable=False)
    metadata_json = Column("metadata", JSON, key="metadata_json", nullable=True)
    vector_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    requirement = relationship("Requirement", back_populates="versions")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(64), nullable=False, default="manual")
    status = Column(String(32), nullable=False, default="pending_index", index=True)
    vector_id = Column(String(512), nullable=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="knowledge_documents")


class TestScenario(Base):
    __tablename__ = "test_scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    external_id = Column(String, nullable=True)
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
    external_id = Column(String, nullable=True)
    source = Column(String, nullable=False, default="generated")
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
    custom_fields_json = Column("custom_fields", JSON, key="custom_fields_json", nullable=False, default=dict)
    custom_field_schema_json = Column(
        "custom_field_schema", JSON, key="custom_field_schema_json", nullable=False, default=dict
    )
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
    external_id = Column(String, nullable=True)
    source = Column(String, nullable=False, default="generated")
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
    vector_id = Column(String, nullable=True)
    custom_fields_json = Column("custom_fields", JSON, key="custom_fields_json", nullable=False, default=dict)
    custom_field_schema_json = Column(
        "custom_field_schema", JSON, key="custom_field_schema_json", nullable=False, default=dict
    )

    test_case = relationship("TestCase", back_populates="versions")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_level = Column(String, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    quality_evaluation_id = Column(
        UUID(as_uuid=True), ForeignKey("quality_evaluations.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    source_event_id = Column(
        UUID(as_uuid=True), ForeignKey("outbox_events.id", ondelete="SET NULL"), nullable=True, unique=True
    )
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
    target_level = Column(String(32), nullable=False, default="requirement", index=True)
    target_id = Column(UUID(as_uuid=True), nullable=True, index=True)
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


class IntegrationSchedule(Base):
    __tablename__ = "integration_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    integration_type = Column(String(32), nullable=False, default="jira")
    configuration = Column(JSON, nullable=False, default=dict)
    interval_seconds = Column(Integer, nullable=False, default=3600)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    next_run_at = Column(DateTime, nullable=False, index=True)
    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(String(32), nullable=True)
    last_error_type = Column(String(255), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


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


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    dedupe_key = Column(String, nullable=False, unique=True)
    category = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="open", index=True)
    delivery_status = Column(String, nullable=False, default="not_configured", index=True)
    acknowledged_by = Column(String, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ApiRateLimit(Base):
    __tablename__ = "api_rate_limits"

    bucket_key = Column(String, primary_key=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    request_count = Column(Integer, nullable=False, default=0)


class SemanticCalibrationRun(Base):
    __tablename__ = "semantic_calibration_runs"
    __table_args__ = (UniqueConstraint("project_id", "dataset_digest", name="uq_semantic_calibration_dataset"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_digest = Column(String, nullable=False)
    sample_count = Column(Integer, nullable=False)
    label_distribution = Column(JSON, nullable=False, default=dict)
    previous_thresholds = Column(JSON, nullable=False, default=dict)
    proposed_thresholds = Column(JSON, nullable=False, default=dict)
    metrics = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="proposed", index=True)
    requested_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    applied_at = Column(DateTime, nullable=True)


class SearchEvent(Base):
    __tablename__ = "search_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    mode = Column(String(32), nullable=False)
    entity_type = Column(String(32), nullable=True)
    result_count = Column(Integer, nullable=False, default=0)
    offset = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    semantic_fallback = Column(Boolean, nullable=False, default=False)
    requested_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class SearchJudgment(Base):
    __tablename__ = "search_judgments"
    __table_args__ = (
        UniqueConstraint("search_event_id", "entity_type", "entity_id", name="uq_search_judgment_result"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_event_id = Column(
        UUID(as_uuid=True), ForeignKey("search_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type = Column(String(32), nullable=False)
    entity_id = Column(String(255), nullable=False)
    rank = Column(Integer, nullable=False)
    judgment = Column(String(32), nullable=False)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("project_id", "created_by", "name", name="uq_saved_search_owner_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    query = Column(Text, nullable=False)
    mode = Column(String(32), nullable=False, default="hybrid")
    entity_type = Column(String(32), nullable=True)
    created_by = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


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


class ApprovalWorkflowRun(Base):
    __tablename__ = "approval_workflow_runs"
    __table_args__ = (
        UniqueConstraint(
            "test_case_id", "test_case_version", "content_sha256", name="uq_approval_workflow_artifact"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    test_case_id = Column(
        UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_version = Column(Integer, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    policy_snapshot = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="awaiting_evaluation", index=True)
    current_stage = Column(Integer, nullable=False, default=0)
    quality_evaluation_id = Column(
        UUID(as_uuid=True), ForeignKey("quality_evaluations.id", ondelete="SET NULL"), nullable=True
    )
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    decisions = relationship(
        "ApprovalWorkflowDecision", back_populates="workflow_run", cascade="all, delete-orphan"
    )


class ApprovalWorkflowDecision(Base):
    __tablename__ = "approval_workflow_decisions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "stage_index", "decided_by", name="uq_approval_workflow_stage_actor"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_run_id = Column(
        UUID(as_uuid=True), ForeignKey("approval_workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_index = Column(Integer, nullable=False)
    stage_name = Column(String(255), nullable=False)
    decision = Column(String(32), nullable=False)
    decided_by = Column(String(255), nullable=False)
    decided_role = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workflow_run = relationship("ApprovalWorkflowRun", back_populates="decisions")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=False, unique=True)
    role = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=1)
    settings_json = Column("settings", JSON, key="settings_json", nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project_memberships = relationship("ProjectMembership", back_populates="user", cascade="all, delete-orphan")
    organization_memberships = relationship("OrganizationMembership", back_populates="user", cascade="all, delete-orphan")


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
