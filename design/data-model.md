# Data Model

## Entities

### Requirement
- `id` (uuid)
- `external_id` (jira id or document id)
- `title`
- `description`
- `source` (`jira` / `upload` / `manual`)
- `status` (`draft` / `generated` / `reviewed` / `archived`)
- `version`
- `created_at`
- `updated_at`
- `vector_id`

### TestScenario
- `id` (uuid)
- `requirement_id` (fk -> Requirement.id)
- `external_id` (optional historical repository identity)
- `title`
- `description`
- `priority` (`low` / `medium` / `high` / `critical`)
- `severity` (`minor` / `major` / `critical`)
- `category` (e.g. `functional`, `ui`, `security`)
- `type` (e.g. `smoke`, `regression`, `integration`)
- `status` (`draft` / `approved` / `deprecated`)
- `version`
- `vector_id`
- `created_at`
- `updated_at`

### TestCase
- `id` (uuid)
- `scenario_id` (fk -> TestScenario.id)
- `requirement_id` (fk -> Requirement.id)
- `external_id` (optional historical repository identity)
- `source` (`generated` / `historical_import`)
- `title`
- `description`
- `prerequisite`
- `priority`
- `severity`
- `category`
- `type`
- `status` (`draft` / `approved` / `deprecated` / `updated`)
- `version` (integer)
- `approved_at`
- `vector_id`
- `created_at`
- `updated_at`

#### TestCaseStep
- `id` (uuid)
- `test_case_id` (fk -> TestCase.id)
- `step_number` (int)
- `action`
- `expected_result`
- `created_at`
- `updated_at`

### Feedback
- `id` (uuid)
- `target_level` (`requirement` / `scenario` / `test_case`)
- `target_id` (requirement_id / scenario_id / test_case_id)
- `source` (`user` / `system`)
- `feedback_type` (`revise` / `generate_new` / `deprecate` / `accept` / `reject`)
- `comment`
- `created_by`
- `created_at`
- `vector_id`

### ApprovalRecord
- `id` (uuid)
- `target_level` (`scenario` / `test_case` / `requirement`)
- `target_id`
- `approved_by`
- `approved_at`
- `version`
- `status`
- `notes`

### ImportMappingProfile
- `id` (uuid)
- `project_id` (fk -> Project.id)
- `name`
- `entity_type` (`requirement` / `test_case`)
- `configuration` (validated JSON mapping, transforms, custom fields, and import policies)
- `active`
- `created_by`
- `created_at`
- `updated_at`

Company-specific requirement fields are stored under `Requirement.metadata.custom_fields`. Company-specific test-case
fields are stored in `TestCase.custom_fields` and copied into every immutable `TestCaseVersion` snapshot.

## Relationships

- Requirement 1..* TestScenario
- TestScenario 1..* TestCase
- TestCase 1..* TestCaseStep
- Requirement/TestScenario/TestCase 1..* Feedback
- Requirement/TestScenario/TestCase 1..* ApprovalRecord

## Vector storage strategy

- Each Requirement, TestScenario, TestCase, and Feedback item has an embedding stored in vector DB.
- Approved test cases and requirements are searchable for RAG.
- Feedback embeddings can be used to retrieve related generation context.

## Versioning rules

- Every approved test case increments version.
- Every Jira requirement content change increments version and preserves an immutable requirement snapshot.
- Revisions create a new version while preserving older versions.
- Deprecated cases remain available for audit but are excluded from active generation.
- Every immutable test-case version has its own stable `test_case:<id>:v<version>` vector ID and is indexed from
  the stored snapshot rather than the mutable current row.
