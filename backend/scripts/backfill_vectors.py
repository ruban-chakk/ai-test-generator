from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import asdict

from app.db import AsyncSessionLocal
from app.models import Project
from app.services.vector_backfill import enqueue_vector_backfill


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Queue idempotent PostgreSQL-to-Pinecone vector reconciliation events."
    )
    parser.add_argument("--project-id", type=uuid.UUID)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Requeue every vectorizable record, including records already marked indexed.",
    )
    parser.add_argument("--actor", default="vector-backfill-cli")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict:
    async with AsyncSessionLocal() as db:
        if args.project_id is not None and await db.get(Project, args.project_id) is None:
            raise ValueError("project not found")
        result = await enqueue_vector_backfill(
            db,
            project_id=args.project_id,
            include_all=args.all,
            actor=args.actor.strip() or "vector-backfill-cli",
        )
        return asdict(result)


def main() -> None:
    args = parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
