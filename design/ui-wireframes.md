# UI Wireframes and Component Map

## Design principles

- Rich, enterprise-grade interface
- Clear hierarchy and navigation
- Fast review and approval actions
- Contextual feedback capture
- Visual impact analysis and audit history

## Primary screens

### 1. Login / landing
- Authentication screen with SSO or username/password.
- Option to return to last open requirement or dashboard.

### 2. Requirement dashboard
- Header with search bar, filters, and action buttons.
- Cards or table rows for requirements showing:
  - title
  - source
  - status badge (draft/generated/reviewed/approved)
  - last updated
  - approval progress
  - impact risk score
- Sidebar/toolbar with quick filters by status, priority, category, and owner.
- Add requirement button.

### 3. Requirement detail page
- Top summary panel with requirement metadata, description, and status.
- Tabs:
  - Overview
  - Scenarios
  - Test Cases
  - Feedback
  - Impact Analysis
  - History
- Action bar with `Generate`, `Refresh`, `Add Feedback`, `Run Impact Analysis`.

### 4. Scenarios tab
- Scenario cards with:
  - title
  - description
  - tags: priority, severity, category, type
  - status pill
  - version badge
  - approve/reject buttons
- Expandable scenario panel to show nested test cases.
- Add/replace scenario options.

### 5. Test cases tab
- Test case cards grouped by scenario.
- Each card shows:
  - title and status
  - prerequisite
  - tag chips for priority, severity, category, type
  - version and approved date
  - approve/reject buttons
- Step table inside each card:
  - step number
  - action
  - expected result
- Inline edit and comment button.

### 6. Feedback modal
- Opens on requirement, scenario, or test case.
- Fields:
  - target label
  - feedback type dropdown
  - freeform comment area
  - optional severity / impact tags
- Submit and cancel buttons.

### 7. Impact analysis page
- Summary panel with duplicate count, deprecation recommendations, update candidates.
- Visual similarity chart or weighted list.
- Candidate cards with:
  - entity type
  - title
  - similarity score
  - recommended action
- Actions: `Archive duplicate`, `Mark deprecated`, `Review update`.

### 8. History / audit tab
- Timeline of actions:
  - generation events
  - approvals/rejections
  - feedback submissions
  - version updates
- Filter by actor, action type, or date.

## Component map

### Layout components
- `AppShell`
- `Header`
- `Sidebar`
- `Breadcrumbs`
- `PageContainer`

### Requirement components
- `RequirementDashboard`
- `RequirementCard`
- `RequirementDetailPanel`
- `RequirementMetadataPanel`
- `RequirementActionBar`

### Scenario components
- `ScenarioList`
- `ScenarioCard`
- `ScenarioTagRow`
- `ScenarioActions`

### Test case components
- `TestCaseList`
- `TestCaseCard`
- `TestCaseTagRow`
- `TestCaseStepTable`
- `TestCaseActionBar`

### Feedback components
- `FeedbackModal`
- `FeedbackList`
- `FeedbackItem`
- `FeedbackSummary`

### Impact components
- `ImpactSummaryCard`
- `ImpactCandidateList`
- `ImpactCandidateCard`
- `SimilarityChart`

### Audit components
- `HistoryTimeline`
- `AuditItem`
- `ActivityFilter`

### Shared UI primitives
- `StatusBadge`
- `TagChip`
- `IconButton`
- `ModalDialog`
- `SearchInput`
- `FilterPanel`
- `DataTable`
- `Loader`
- `NotificationBanner`

## Rich UI features

- Collapsible tree view of scenarios and cases
- Tag-based filtering and quick status toggles
- Side-by-side compare for existing vs generated cases
- Inline edit controls for case content
- Action strip for bulk approve/reject
- Review progress meter for each requirement
- Swipe-able cards or keyboard shortcuts for power users
- Rich text rendering for requirement descriptions and expected results

## Page flow

1. User lands on requirement dashboard and filters open work.
2. User opens a requirement detail page.
3. User reviews scenarios in the Scenarios tab.
4. User expands a scenario to review nested test cases.
5. User approves/rejects cases and submits feedback.
6. User runs impact analysis and resolves duplicates.
7. User reviews history and audit trail before final signoff.

## Notes

The UI should feel enterprise-ready with a polished layout, consistent spacing, and accessible controls. Focus on a data-rich experience that makes inspection and decision-making fast.