-- PostgreSQL schema migration for AI Test Case Generator

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

CREATE TABLE IF NOT EXISTS requirements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id varchar,
  title text NOT NULL,
  description text NOT NULL,
  source varchar NOT NULL,
  status varchar NOT NULL DEFAULT 'draft',
  metadata jsonb,
  vector_id varchar,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_requirements_status ON requirements(status);
CREATE INDEX IF NOT EXISTS idx_requirements_external_id ON requirements(external_id);
CREATE INDEX IF NOT EXISTS idx_requirements_title_trgm ON requirements USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS test_scenarios (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  requirement_id uuid NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
  title text NOT NULL,
  description text NOT NULL,
  priority varchar,
  severity varchar,
  category varchar,
  type varchar,
  status varchar NOT NULL DEFAULT 'draft',
  version integer NOT NULL DEFAULT 1,
  vector_id varchar,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scenarios_requirement_id ON test_scenarios(requirement_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_status ON test_scenarios(status);

CREATE TABLE IF NOT EXISTS test_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_id uuid NOT NULL REFERENCES test_scenarios(id) ON DELETE CASCADE,
  requirement_id uuid NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
  title text NOT NULL,
  description text NOT NULL,
  prerequisite text,
  priority varchar,
  severity varchar,
  category varchar,
  type varchar,
  status varchar NOT NULL DEFAULT 'draft',
  version integer NOT NULL DEFAULT 1,
  approved_at timestamptz,
  locked boolean NOT NULL DEFAULT false,
  repository_status varchar NOT NULL DEFAULT 'draft',
  repository_synced_at timestamptz,
  vector_id varchar,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS locked boolean NOT NULL DEFAULT false;
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS repository_status varchar NOT NULL DEFAULT 'draft';
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS repository_synced_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_test_cases_scenario_id ON test_cases(scenario_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_requirement_id ON test_cases(requirement_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_status ON test_cases(status);
CREATE INDEX IF NOT EXISTS idx_test_cases_repository_status ON test_cases(repository_status);
CREATE INDEX IF NOT EXISTS idx_test_cases_title_trgm ON test_cases USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS test_case_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  test_case_id uuid NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
  step_number integer NOT NULL,
  action text NOT NULL,
  expected_result text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_steps_test_case_id ON test_case_steps(test_case_id);
CREATE INDEX IF NOT EXISTS idx_steps_test_case_step_number ON test_case_steps(test_case_id, step_number);

CREATE TABLE IF NOT EXISTS test_case_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  test_case_id uuid NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
  requirement_id uuid NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
  scenario_id uuid NOT NULL REFERENCES test_scenarios(id) ON DELETE CASCADE,
  version integer NOT NULL,
  title text NOT NULL,
  description text NOT NULL,
  prerequisite text,
  priority varchar,
  severity varchar,
  category varchar,
  type varchar,
  status varchar NOT NULL,
  approved_by varchar NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  notes text,
  steps_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_test_case_versions_case ON test_case_versions(test_case_id, version);

CREATE TABLE IF NOT EXISTS feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_level varchar NOT NULL,
  target_id uuid NOT NULL,
  source varchar NOT NULL,
  feedback_type varchar NOT NULL,
  comment text NOT NULL,
  created_by varchar NOT NULL,
  status varchar NOT NULL DEFAULT 'open',
  resolved_at timestamptz,
  resolution_notes text,
  vector_id varchar,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE feedback ADD COLUMN IF NOT EXISTS status varchar NOT NULL DEFAULT 'open';
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS resolution_notes text;

CREATE INDEX IF NOT EXISTS idx_feedback_target ON feedback(target_level, target_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created_by ON feedback(created_by);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);

CREATE TABLE IF NOT EXISTS revision_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_id uuid REFERENCES feedback(id) ON DELETE SET NULL,
  target_level varchar NOT NULL,
  target_id uuid NOT NULL,
  action varchar NOT NULL,
  status varchar NOT NULL DEFAULT 'completed',
  created_by varchar NOT NULL,
  notes text,
  source_snapshot jsonb,
  result_snapshot jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_revision_records_target ON revision_records(target_level, target_id);
CREATE INDEX IF NOT EXISTS idx_revision_records_feedback_id ON revision_records(feedback_id);

CREATE TABLE IF NOT EXISTS quality_evaluations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_level varchar NOT NULL,
  target_id uuid NOT NULL,
  score integer NOT NULL,
  status varchar NOT NULL,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  issues jsonb NOT NULL DEFAULT '[]'::jsonb,
  evaluated_by varchar NOT NULL DEFAULT 'system',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quality_evaluations_target ON quality_evaluations(target_level, target_id);
CREATE INDEX IF NOT EXISTS idx_quality_evaluations_status ON quality_evaluations(status);

CREATE TABLE IF NOT EXISTS impact_analyses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  requirement_id uuid REFERENCES requirements(id) ON DELETE SET NULL,
  source_text text NOT NULL,
  similarity_threshold integer NOT NULL DEFAULT 80,
  duplicates jsonb NOT NULL DEFAULT '[]'::jsonb,
  deprecations jsonb NOT NULL DEFAULT '[]'::jsonb,
  updates jsonb NOT NULL DEFAULT '[]'::jsonb,
  risk_score integer NOT NULL DEFAULT 0,
  coverage_score integer NOT NULL DEFAULT 0,
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by varchar NOT NULL DEFAULT 'system',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_impact_analyses_requirement_id ON impact_analyses(requirement_id);
CREATE INDEX IF NOT EXISTS idx_impact_analyses_created_at ON impact_analyses(created_at);

CREATE TABLE IF NOT EXISTS approval_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_level varchar NOT NULL,
  target_id uuid NOT NULL,
  approved_by varchar NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL,
  status varchar NOT NULL,
  notes text
);

CREATE INDEX IF NOT EXISTS idx_approval_records_target ON approval_records(target_level, target_id);

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username varchar NOT NULL UNIQUE,
  email varchar NOT NULL UNIQUE,
  role varchar NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type varchar NOT NULL,
  entity_id uuid,
  action varchar NOT NULL,
  actor varchar NOT NULL,
  details jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_requirements_updated_at
BEFORE UPDATE ON requirements
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_test_scenarios_updated_at
BEFORE UPDATE ON test_scenarios
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_test_cases_updated_at
BEFORE UPDATE ON test_cases
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_test_case_steps_updated_at
BEFORE UPDATE ON test_case_steps
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
