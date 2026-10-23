# Quality judge 502 investigation — 2026-10-23

## Symptom

`POST /api/v1/quality/test_case/{id}` returned `502 Bad Gateway` with `LLM provider returned an invalid structured response`.

## Root cause

`JudgeResult` rejected provider judgments when the reported overall `score` differed by more than 20 points from a simple arithmetic average of the criteria. The API applies configurable weighted scoring server-side, so a valid weighted judgment can legitimately differ from that average. The validator therefore rejected valid structured responses and converted them into a generic 502.

## Fix

Removed the over-strict cross-field average validator. Criterion ranges and required evidence-based fields remain validated. Added a regression test proving that a weighted overall score is accepted.

## Verification

- Targeted evaluation/generation tests: 10 passed.
- Backend service rebuilt and restarted successfully.
- Backend container health: healthy.
