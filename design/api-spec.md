# API / Endpoints Specification

## Base URL

- `/api/v1`

## Authentication

- Bearer token or session-based auth
- Role-based authorization for reviewer, approver, admin

## Endpoints

### Requirements

#### GET /api/v1/requirements
- Description: List requirements with filters
- Query params:
  - `status` (draft, generated, reviewed, archived)
  - `source` (jira, upload, manual)
  - `search`
  - `page`, `limit`
- Response:
  - `requirements: [RequirementSummary]`

#### POST /api/v1/requirements
- Description: Create or ingest a requirement
- Body:
  - `external_id`: string
  - `title`: string
  - `description`: string
  - `source`: string
  - `metadata`: object
- Response:
  - `requirement: RequirementDetail`

#### GET /api/v1/requirements/{requirement_id}
- Description: Retrieve requirement details
- Response:
  - `requirement: RequirementDetail`

#### POST /api/v1/requirements/{requirement_id}/generate
- Description: Generate scenarios and test cases for requirement
- Body:
  - `force`: boolean (optional)
  - `feedback_context`: string (optional)
- Response:
  - `generation_id`: string
  - `status`: string

#### POST /api/v1/requirements/{requirement_id}/refresh
- Description: Re-run generation with updated feedback or data
- Body:
  - `feedback_ids`: [uuid]
- Response:
  - `status`: string

### Scenarios

#### GET /api/v1/requirements/{requirement_id}/scenarios
- Description: List scenarios for requirement
- Response:
  - `scenarios: [TestScenarioSummary]`

#### GET /api/v1/scenarios/{scenario_id}
- Description: Retrieve scenario details
- Response:
  - `scenario: TestScenarioDetail`

#### POST /api/v1/scenarios/{scenario_id}/approve
- Description: Approve a scenario and optionally its cases
- Body:
  - `approve_cases`: boolean
  - `notes`: string
- Response:
  - `approval_record: ApprovalRecord`

#### POST /api/v1/scenarios/{scenario_id}/reject
- Description: Reject a scenario
- Body:
  - `reason`: string
- Response:
  - `status`: string

### Test Cases

#### GET /api/v1/scenarios/{scenario_id}/testcases
- Description: List test cases for a scenario
- Response:
  - `test_cases: [TestCaseSummary]`

#### GET /api/v1/testcases/{test_case_id}
- Description: Retrieve a test case
- Response:
  - `test_case: TestCaseDetail`

#### PUT /api/v1/testcases/{test_case_id}
- Description: Update test case content or metadata
- Body:
  - `title`: string
  - `description`: string
  - `prerequisite`: string
  - `priority`: string
  - `severity`: string
  - `category`: string
  - `type`: string
  - `steps`: [TestCaseStepInput]
- Response:
  - `test_case: TestCaseDetail`

#### POST /api/v1/testcases/{test_case_id}/approve
- Description: Approve a test case
- Body:
  - `notes`: string
- Response:
  - `approval_record: ApprovalRecord`

#### POST /api/v1/testcases/{test_case_id}/reject
- Description: Reject a test case
- Body:
  - `reason`: string
- Response:
  - `status`: string

#### POST /api/v1/testcases/{test_case_id}/version
- Description: Create a new version for a test case
- Body:
  - `changes`: object
  - `notes`: string
- Response:
  - `test_case: TestCaseDetail`

### Feedback

#### POST /api/v1/feedback
- Description: Submit feedback on requirement, scenario, or test case
- Body:
  - `target_level`: requirement | scenario | test_case
  - `target_id`: uuid
  - `feedback_type`: revise | generate_new | deprecate | accept | reject
  - `comment`: string
  - `created_by`: string
- Response:
  - `feedback: FeedbackDetail`

#### GET /api/v1/feedback?target_level=&target_id=
- Description: List feedback entries for a target
- Response:
  - `feedback: [FeedbackDetail]`

### Impact analysis

#### GET /api/v1/requirements/{requirement_id}/impact
- Description: Compute impact analysis for a requirement
- Response:
  - `duplicates: [ImpactCandidate]`
  - `deprecations: [ImpactCandidate]`
  - `updates: [ImpactCandidate]`
  - `similarity_threshold`: number

#### POST /api/v1/impact/analyze
- Description: Analyze a free-form requirement or requirement draft
- Body:
  - `text`: string
  - `context_ids`: [uuid]
- Response:
  - `impact_result: ImpactAnalysisResult`

### Search

#### GET /api/v1/search
- Description: Global search across requirements, scenarios, and test cases
- Query params:
  - `query`: string
  - `entity_type`: requirement | scenario | test_case
  - `status`:
- Response:
  - `results: [SearchResult]`

### Admin / integration

#### POST /api/v1/integrations/jira/import
- Description: Import requirements from a Jira folder abstraction
- Body:
  - `folder_path`: string
- Response:
  - `imported_count`: number

#### POST /api/v1/integrations/test-repo/sync
- Description: Sync approved test cases to the repository
- Body:
  - `repository`: string
  - `branch`: string
- Response:
  - `status`: string

## Data contracts

### RequirementSummary
- `id`: uuid
- `external_id`: string
- `title`: string
- `status`: string
- `source`: string
- `created_at`: datetime
- `updated_at`: datetime

### RequirementDetail
- includes RequirementSummary plus:
- `description`: string
- `metadata`: object
- `scenarios`: [TestScenarioSummary]
- `feedback_count`: number
- `approval_status`: string

### TestScenarioSummary
- `id`: uuid
- `title`: string
- `description`: string
- `priority`: string
- `severity`: string
- `category`: string
- `type`: string
- `status`: string
- `version`: number
- `approved_at`: datetime | null

### TestScenarioDetail
- includes TestScenarioSummary plus:
- `test_cases`: [TestCaseSummary]
- `feedback_count`: number
- `approval_records`: [ApprovalRecord]

### TestCaseSummary
- `id`: uuid
- `title`: string
- `status`: string
- `version`: number
- `priority`: string
- `severity`: string
- `category`: string
- `type`: string
- `approved_at`: datetime | null

### TestCaseDetail
- includes TestCaseSummary plus:
- `description`: string
- `prerequisite`: string
- `steps`: [TestCaseStep]
- `requirement_id`: uuid
- `scenario_id`: uuid
- `feedback_count`: number
- `approval_records`: [ApprovalRecord]

### TestCaseStepInput
- `step_number`: integer
- `action`: string
- `expected_result`: string

### FeedbackDetail
- `id`: uuid
- `target_level`: string
- `target_id`: uuid
- `feedback_type`: string
- `comment`: string
- `created_by`: string
- `created_at`: datetime

### ApprovalRecord
- `id`: uuid
- `target_level`: string
- `target_id`: uuid
- `approved_by`: string
- `approved_at`: datetime
- `version`: integer
- `status`: string
- `notes`: string

### ImpactCandidate
- `entity_id`: uuid
- `entity_type`: requirement | scenario | test_case
- `title`: string
- `similarity`: number
- `reason`: string

### SearchResult
- `entity_type`: string
- `entity_id`: uuid
- `title`: string
- `snippet`: string
- `status`: string

## Error handling

- 400 Bad Request: invalid payload
- 401 Unauthorized: missing or invalid credentials
- 403 Forbidden: insufficient permissions
- 404 Not Found: missing entity
- 500 Internal Server Error: unexpected failure

## Notes

- Every create/update/approve/reject action should be recorded in audit logs.
- Generation and impact endpoints should return `status` and `request_id` for async processing if needed.
- Feedback submissions should optionally support `context_id` to link to AI revision history.
