# UI Flows and Review Experience

## Primary screens

### 1. Requirement list
- Shows each imported requirement
- Status badges: `draft`, `generated`, `reviewed`, `approved`
- Buttons: `Open`, `Generate`, `Impact analysis`

### 2. Requirement details
- Requirement title, description, source, metadata
- Generated test plan summary
- Tabs for `Scenarios`, `Test Cases`, `Feedback`, `Impact Analysis`
- Actions: `Generate`, `Refresh`, `Add feedback`

### 3. Scenario list
- Each scenario card shows:
  - title
  - description
  - tags: priority, severity, category, type
  - status
- Buttons on card: `Approve`, `Reject`, `Feedback`
- Expand to show nested test cases

### 4. Test case list
- Displayed under scenario
- Each test case shows:
  - title
  - prerequisite
  - tags: priority, severity, category, type
  - status and version
- Steps shown in a table:
  - step number
  - action
  - expected result
- Actions: `Approve`, `Reject`, `Feedback`, `View history`

### 5. Feedback modal
- Opens from requirement, scenario, or test case
- Fields:
  - feedback level (auto-filled)
  - comment text
  - action type: `revise`, `generate new`, `deprecate`, `accept`, `reject`
- Submit saves feedback and optionally re-runs a generation pipeline.

### 6. Impact analysis page
- New requirement similarity summary
- Duplicate cases (>= 80% similarity)
- Cases recommended for deprecation
- Cases recommended for update
- Visual match scores and linked test cases

## Review and approval flow

1. User opens a generated requirement
2. They inspect scenarios and cases
3. They approve or reject each test case individually
4. Approval of a case triggers:
   - version increment
   - push to test repo
   - indexing in vector DB
5. Approving a scenario can optionally approve all contained cases
6. Approving the requirement can mark the full plan as reviewed

## Feedback experience

- Feedback button opens a modal on the exact object
- Comments are persisted and displayed in a threaded view
- Feedback should be visible in the requirement and scenario cards
- Feedback can trigger revision suggestions or re-generation

## Duplicate / impact rules in UI

- duplicates are shown as similarity cards with score
- deprecation candidates are shown with a reason summary
- update candidates include overlap details and whether manual review is recommended

## Usability notes

- Use color-coded tags for priority/severity/category/type
- Provide collapse/expand controls for scenario -> test case hierarchies
- Show `approved` vs `draft` vs `deprecated` clearly
- Keep the approval step lightweight and reversible via history
