# Bulk job stuck — 2026-10-26

- Symptom: batch `ef672f5b-6f8e-4780-8aeb-ab38e1777885` stayed at `processing`, 0/100.
- Root causes: the worker used an all-zero synthetic user ID, violating `ai_usage_records.user_id`; its error path updated a session still in rollback state. Separately, nested JSON item mutations were not detected by SQLAlchemy, so the first queued item was repeatedly selected while only the aggregate counter advanced.
- Fix: workers now resolve the requesting user ID, roll back and reacquire the job on item errors, deep-copy JSON items, and explicitly call `flag_modified(job, "result")`.
- Recovery: the exact job was re-queued with counters reset after the fix. Live verification showed item 1 completed, item 2 completed, item 3 processing, and aggregate progress advancing.
