"""Add governed organization administration, AI configuration, and cost tracking.

Revision ID: 20261022_0020
Revises: 20261022_0019
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0020"
down_revision = "20261022_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE organizations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          name varchar(255) NOT NULL UNIQUE,
          slug varchar(128) NOT NULL UNIQUE,
          status varchar(32) NOT NULL DEFAULT 'active',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_organization_status CHECK (status IN ('active', 'suspended', 'archived'))
        );

        INSERT INTO organizations (id, name, slug) VALUES ('00000000-0000-0000-0000-000000000001', 'Default Organization', 'default')
        ON CONFLICT (slug) DO NOTHING;

        ALTER TABLE projects ADD COLUMN organization_id uuid;
        ALTER TABLE projects ADD COLUMN cost_center varchar(128) NOT NULL DEFAULT 'unassigned';
        UPDATE projects SET organization_id = (SELECT id FROM organizations WHERE slug = 'default')
          WHERE organization_id IS NULL;
        ALTER TABLE projects ALTER COLUMN organization_id SET NOT NULL;
        ALTER TABLE projects ADD CONSTRAINT fk_projects_organization
          FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE RESTRICT;
        CREATE INDEX idx_projects_organization ON projects(organization_id);
        ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_name_key;
        ALTER TABLE projects ADD CONSTRAINT uq_project_organization_name UNIQUE (organization_id, name);

        CREATE TABLE organization_memberships (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role varchar(32) NOT NULL DEFAULT 'member',
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_organization_membership UNIQUE (organization_id, user_id),
          CONSTRAINT ck_organization_membership_role CHECK (role IN ('org_admin', 'member'))
        );
        CREATE INDEX idx_organization_memberships_organization ON organization_memberships(organization_id);
        CREATE INDEX idx_organization_memberships_user ON organization_memberships(user_id);

        INSERT INTO organization_memberships (organization_id, user_id, role)
        SELECT o.id, u.id, CASE WHEN u.role = 'admin' THEN 'org_admin' ELSE 'member' END
        FROM organizations o CROSS JOIN users u
        WHERE o.slug = 'default'
        ON CONFLICT (organization_id, user_id) DO NOTHING;

        UPDATE project_memberships SET role = 'project_admin' WHERE role = 'admin';

        CREATE TABLE invitations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
          email varchar(320) NOT NULL,
          organization_role varchar(32) NOT NULL DEFAULT 'member',
          project_role varchar(64),
          token_hash varchar(64) NOT NULL UNIQUE,
          status varchar(32) NOT NULL DEFAULT 'pending',
          invited_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          expires_at timestamptz NOT NULL,
          accepted_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_invitation_org_role CHECK (organization_role IN ('org_admin', 'member')),
          CONSTRAINT ck_invitation_status CHECK (status IN ('pending', 'accepted', 'revoked', 'expired'))
        );
        CREATE INDEX idx_invitations_organization ON invitations(organization_id);
        CREATE INDEX idx_invitations_project ON invitations(project_id);
        CREATE INDEX idx_invitations_email ON invitations(email);
        CREATE INDEX idx_invitations_status ON invitations(status);

        CREATE TABLE ai_model_configurations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          scope_type varchar(16) NOT NULL,
          scope_id uuid,
          generation_model varchar(255) NOT NULL,
          judge_model varchar(255) NOT NULL,
          embedding_model varchar(255) NOT NULL,
          vector_provider varchar(64) NOT NULL DEFAULT 'pinecone',
          vector_index varchar(255) NOT NULL,
          vector_namespace varchar(255) NOT NULL,
          vector_host varchar(500),
          credential_reference varchar(255),
          evaluation_weights jsonb NOT NULL DEFAULT '{}'::jsonb,
          pricing jsonb NOT NULL DEFAULT '{}'::jsonb,
          updated_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ai_model_scope CHECK (
            (scope_type = 'app' AND scope_id IS NULL) OR
            (scope_type IN ('organization', 'project') AND scope_id IS NOT NULL)
          )
        );
        CREATE UNIQUE INDEX uq_ai_model_configuration_scope
          ON ai_model_configurations(scope_type, COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid));

        CREATE TABLE ai_usage_records (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
          user_id uuid REFERENCES users(id) ON DELETE SET NULL,
          operation varchar(64) NOT NULL,
          model varchar(255) NOT NULL,
          input_tokens integer NOT NULL DEFAULT 0,
          output_tokens integer NOT NULL DEFAULT 0,
          cost_micros bigint NOT NULL DEFAULT 0,
          metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ai_usage_tokens CHECK (input_tokens >= 0 AND output_tokens >= 0),
          CONSTRAINT ck_ai_usage_cost CHECK (cost_micros >= 0)
        );
        CREATE INDEX idx_ai_usage_organization ON ai_usage_records(organization_id, created_at);
        CREATE INDEX idx_ai_usage_project ON ai_usage_records(project_id, created_at);
        CREATE INDEX idx_ai_usage_user ON ai_usage_records(user_id, created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS ai_usage_records;
        DROP TABLE IF EXISTS ai_model_configurations;
        DROP TABLE IF EXISTS invitations;
        DROP TABLE IF EXISTS organization_memberships;
        ALTER TABLE projects DROP CONSTRAINT IF EXISTS uq_project_organization_name;
        ALTER TABLE projects ADD CONSTRAINT projects_name_key UNIQUE (name);
        ALTER TABLE projects DROP CONSTRAINT IF EXISTS fk_projects_organization;
        ALTER TABLE projects DROP COLUMN IF EXISTS cost_center;
        ALTER TABLE projects DROP COLUMN IF EXISTS organization_id;
        DROP TABLE IF EXISTS organizations;
        """
    )
