# Mock ingestion data

These fixtures provide linked Jira-style user stories and approved historical test cases for the demo commerce project.

## Import order

1. Sign in as an `approver` or `admin` and select the destination project.
2. Open **Operations > File import** and upload `mock-jira-user-stories.json`.
3. Wait until the requirement import reports six created or existing requirements.
4. Open **Operations > Historical test cases** and upload `mock-historical-test-cases.json`.
5. The historical import should report thirteen test cases and queued vector events.
6. Run the outbox worker so the requirements and approved test cases are embedded and written to Pinecone.

The test cases link to requirements through `requirement_external_id`. Importing the test-case file before its requirements intentionally fails validation.

Both imports are idempotent for the same project and external IDs, so the files can be uploaded again without creating duplicates.
