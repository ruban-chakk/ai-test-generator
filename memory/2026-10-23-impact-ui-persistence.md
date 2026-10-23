# Impact analysis UI and requirement-detail loading — 2026-10-23

## Symptoms

- The “Analyze scenario” action could visually overlap the scenario column content.
- Running impact analysis appeared successful, but refreshing the requirement page removed the displayed result.
- Requirement details waited on supplementary history data, making the page feel slow to open.

## Root cause

- The scenario action and scenario label were rendered in the same table cell without a layout wrapper.
- The requirement-detail page kept the latest impact response only in React state and never loaded persisted impact records on initial render.
- Initial rendering awaited the history request after loading the requirement.

## Fix

- Added a stacked `.impact-inline-cell` layout for scenario text and its action.
- Added target-scoped impact listing and loaded the latest requirement-level result from `/api/v1/impact?target_level=requirement&target_id=...` after the requirement renders.
- Made history and impact loading supplementary asynchronous requests so requirement content renders as soon as the requirement request completes.

## Verification

- Frontend tests: 16 passed.
- Frontend production build: passed.
- Backend compile and targeted impact/evaluation workflow tests: 6 passed.
- Docker backend/frontend images rebuilt and containers restarted successfully.
- Running backend container is healthy; OpenAPI includes the generic impact endpoint and scenario impact endpoint.
