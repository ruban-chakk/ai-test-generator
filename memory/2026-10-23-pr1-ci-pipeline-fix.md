# PR #1 CI pipeline investigation — 2026-10-23

## Symptoms

- GitHub Actions Quality run failed in the frontend Playwright test for Operations.
- Backend PostgreSQL outbox tests reported pending events and missing indexed artifacts.
- Approval workflow integration test failed because its evaluator mock did not accept prompt-template overrides.

## Root causes

- The Operations UI was split into a settings hub and focused routes, but the E2E still asserted the removed legacy all-sections page. The test also navigated before the asynchronous admin-context request had exposed the protected Operations route.
- PostgreSQL integration tests shared a disposable database. Earlier tests left pending outbox rows, so the outbox suite claimed an orphaned event before its own fixture event.
- The approval test mock used the pre-prompt-governance builder signature.

## Fixes

- Updated Operations E2E coverage to use the admin navigation and focused Monitoring, Dependency health, Outbox, Compliance, Calibration, and Requirement files routes.
- Updated the evaluator mock to accept keyword prompt-template overrides.
- Isolated outbox integration scenarios by clearing the shared disposable queue before seeding fixtures. Production outbox behavior remains unchanged.
- Added exception trace logging while retaining sanitized error types in persisted outbox records.

## Verification

- Frontend unit tests: 16 passed.
- Frontend production build: passed.
- Frontend Playwright E2E: 3 passed.
- Backend targeted tests: 12 passed locally.
- GitHub Actions Quality run `39933600703` (run 4): backend and frontend passed.

