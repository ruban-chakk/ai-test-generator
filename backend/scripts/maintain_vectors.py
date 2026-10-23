from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import asdict

from app.core.config import settings
from app.db import AsyncSessionLocal
from app.models import Project
from app.services.generation import PineconeVectorStore
from app.services.vector_maintenance import reconcile_vectors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit PostgreSQL-to-Pinecone drift, storage usage, and optional repairs."
    )
    parser.add_argument("--project-id", type=uuid.UUID)
    parser.add_argument(
        "--repair-missing",
        action=argparse.BooleanOptionalAction,
        default=settings.vector_maintenance_repair_missing,
    )
    parser.add_argument(
        "--delete-orphans",
        action=argparse.BooleanOptionalAction,
        default=settings.vector_maintenance_delete_orphans,
    )
    parser.add_argument("--actor", default="vector-maintenance-cli")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=0,
        help="Repeat forever at this interval; zero runs once.",
    )
    return parser.parse_args()


async def run_once(args: argparse.Namespace) -> dict:
    async with AsyncSessionLocal() as db:
        if args.project_id is not None and await db.get(Project, args.project_id) is None:
            raise ValueError("project not found")
        result = await reconcile_vectors(
            db,
            PineconeVectorStore(settings),
            project_id=args.project_id,
            repair_missing=args.repair_missing,
            delete_orphans=args.delete_orphans,
            actor=args.actor.strip() or "vector-maintenance-cli",
        )
        return asdict(result)


async def run(args: argparse.Namespace) -> None:
    if args.interval_seconds < 0:
        raise ValueError("interval-seconds cannot be negative")
    while True:
        print(json.dumps(await run_once(args), sort_keys=True, default=str), flush=True)
        if args.interval_seconds == 0:
            return
        await asyncio.sleep(max(60, args.interval_seconds))


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
