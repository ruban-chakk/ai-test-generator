# Backend Setup

## Install dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment

Copy `.env.example` to `.env` and configure the database and Pinecone values.

## Database migration

Apply the SQL migration directly in PostgreSQL or integrate with Alembic.

```bash
psql $POSTGRES_DSN -f backend/migrations/001_create_schema.sql
```
