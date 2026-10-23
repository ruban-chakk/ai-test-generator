# DB Schema and Pinecone Index Design

## PostgreSQL schema

### requirements
- `id` uuid PRIMARY KEY
- `external_id` varchar
- `title` text NOT NULL
- `description` text NOT NULL
- `source` varchar NOT NULL
- `status` varchar NOT NULL
- `version` integer NOT NULL DEFAULT 1
- `metadata` jsonb
- `vector_id` varchar NULL
- `created_at` timestamptz NOT NULL DEFAULT now()
- `updated_at` timestamptz NOT NULL DEFAULT now()

Indexes:
- `idx_requirements_status` on `status`
- `idx_requirements_external_id` on `external_id`
- `idx_requirements_title_trgm` on `title` using gin(trgm)

### requirement_versions
- `id` uuid PRIMARY KEY
- `requirement_id` uuid REFERENCES requirements(id) ON DELETE CASCADE
- `project_id` uuid REFERENCES projects(id) ON DELETE SET NULL
- `version` integer NOT NULL
- immutable external ID, title, description, source, status, and metadata snapshot
- `vector_id` varchar NULL

Indexes:
- unique (`requirement_id`, `version`)
- unique non-null `vector_id`
- `project_id`

### test_scenarios
- `id` uuid PRIMARY KEY
- `requirement_id` uuid REFERENCES requirements(id) ON DELETE CASCADE
- `external_id` varchar NULL
- `title` text NOT NULL
- `description` text NOT NULL
- `priority` varchar
- `severity` varchar
- `category` varchar
- `type` varchar
- `status` varchar NOT NULL
- `version` integer NOT NULL DEFAULT 1
- `vector_id` varchar NULL
- `created_at` timestamptz NOT NULL DEFAULT now()
- `updated_at` timestamptz NOT NULL DEFAULT now()

Indexes:
- `idx_scenarios_requirement_id` on `requirement_id`
- `idx_scenarios_status` on `status`

### test_cases
- `id` uuid PRIMARY KEY
- `scenario_id` uuid REFERENCES test_scenarios(id) ON DELETE CASCADE
- `requirement_id` uuid REFERENCES requirements(id) ON DELETE CASCADE
- `external_id` varchar NULL
- `source` varchar NOT NULL DEFAULT `generated`
- `title` text NOT NULL
- `description` text NOT NULL
- `prerequisite` text
- `priority` varchar
- `severity` varchar
- `category` varchar
- `type` varchar
- `status` varchar NOT NULL
- `version` integer NOT NULL DEFAULT 1
- `approved_at` timestamptz NULL
- `vector_id` varchar NULL
- `created_at` timestamptz NOT NULL DEFAULT now()
- `updated_at` timestamptz NOT NULL DEFAULT now()

Indexes:
- `idx_test_cases_scenario_id` on `scenario_id`
- `idx_test_cases_requirement_id` on `requirement_id`
- `idx_test_cases_status` on `status`
- `idx_test_cases_title_trgm` on `title` using gin(trgm)

### test_case_steps
- `id` uuid PRIMARY KEY
- `test_case_id` uuid REFERENCES test_cases(id) ON DELETE CASCADE
- `step_number` integer NOT NULL
- `action` text NOT NULL
- `expected_result` text NOT NULL
- `created_at` timestamptz NOT NULL DEFAULT now()
- `updated_at` timestamptz NOT NULL DEFAULT now()

Indexes:
- `idx_steps_test_case_id` on `test_case_id`
- `idx_steps_test_case_step_number` on (`test_case_id`, `step_number`)

### feedback
- `id` uuid PRIMARY KEY
- `target_level` varchar NOT NULL
- `target_id` uuid NOT NULL
- `source` varchar NOT NULL
- `feedback_type` varchar NOT NULL
- `comment` text NOT NULL
- `created_by` varchar NOT NULL
- `vector_id` varchar NULL
- `created_at` timestamptz NOT NULL DEFAULT now()

Indexes:
- `idx_feedback_target` on (`target_level`, `target_id`)
- `idx_feedback_created_by` on `created_by`

### approval_records
- `id` uuid PRIMARY KEY
- `target_level` varchar NOT NULL
- `target_id` uuid NOT NULL
- `approved_by` varchar NOT NULL
- `approved_at` timestamptz NOT NULL DEFAULT now()
- `version` integer NOT NULL
- `status` varchar NOT NULL
- `notes` text

Indexes:
- `idx_approval_records_target` on (`target_level`, `target_id`)

### users
- `id` uuid PRIMARY KEY
- `username` varchar UNIQUE NOT NULL
- `email` varchar UNIQUE NOT NULL
- `role` varchar NOT NULL
- `created_at` timestamptz NOT NULL DEFAULT now()
- `updated_at` timestamptz NOT NULL DEFAULT now()

### audit_logs
- `id` uuid PRIMARY KEY
- `entity_type` varchar NOT NULL
- `entity_id` uuid NULL
- `action` varchar NOT NULL
- `actor` varchar NOT NULL
- `details` jsonb
- `created_at` timestamptz NOT NULL DEFAULT now()

Indexes:
- `idx_audit_logs_entity` on (`entity_type`, `entity_id`)

## Pinecone index design

### Index name
- `ai-testgen-embeddings`

### Dimension
- `1536` (or matching embedding model)

### Metric
- `cosine`
- use `dotproduct` if the embedding model requires it

### Metadata fields
- `entity_type`: requirement | scenario | test_case | feedback
- `entity_id`: uuid
- `requirement_id`: uuid
- `scenario_id`: uuid
- `status`: draft | approved | deprecated | updated
- `source`: jira | upload | manual | system
- `priority`: low | medium | high | critical
- `severity`: minor | major | critical
- `category`: functional | ui | security | regression | integration
- `type`: smoke | regression | integration | exploratory
- `version`: integer
- `created_at`: timestamp
- `approved_at`: timestamp or null
- `title`: text
- `text_snippet`: text

### Vector storage strategy
- Store one versioned embedding per immutable requirement and approved test-case snapshot, plus one embedding per
  feedback entity.
- For requirements, store the full requirement description.
- For scenarios, store the scenario title + description.
- For test cases, store title, description, prerequisite, and step summaries.
- For feedback, store the feedback comment plus target metadata.

### Query patterns
- Retrieval for generation:
  - filter on `entity_type` in [requirement, test_case] and `status` = approved
  - query by requirement embedding
- Duplicate detection:
  - query nearest neighbors of generated test cases among approved `test_case` entities
  - use `similarity_threshold` = 0.80
- Impact analysis:
  - query by new requirement against approved `test_case` and `scenario`
  - optionally filter by `category` or `priority`
- Feedback retrieval:
  - query feedback embeddings when re-running generation
  - filter on `target_id` and `target_level`

### Index maintenance
- Create or upsert a stable version vector when a test case is approved or imported; never overwrite an older
  approved-version vector.
- Delete or mark deprecated embeddings when a case is retired.
- Rebuild index periodically if metadata schema changes significantly.

## Data consistency
- Use PostgreSQL foreign keys to enforce relationships.
- Keep `vector_id` in PostgreSQL to map entities to Pinecone vectors.
- Commit canonical state and an outbox intent in one PostgreSQL transaction; never attempt a database/Pinecone dual write.
- Workers upsert stable vector IDs, recover stale claims, retry transient failures, and retain sanitized failure types.
- The vector reconciliation command recreates missing or failed outbox intents without making provider calls in the
  database transaction.

## Example table DDL

```sql
CREATE TABLE requirements (
  id uuid PRIMARY KEY,
  external_id varchar,
  title text NOT NULL,
  description text NOT NULL,
  source varchar NOT NULL,
  status varchar NOT NULL,
  metadata jsonb,
  vector_id varchar,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```
