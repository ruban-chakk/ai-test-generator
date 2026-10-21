from __future__ import annotations

import argparse
import asyncio

from app.db import AsyncSessionLocal
from app.services.mapped_import_jobs import MappedImportJobProcessor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process resumable mapped-import batches.")
    parser.add_argument("--once", action="store_true", help="Process at most one batch and exit.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    processor = MappedImportJobProcessor(AsyncSessionLocal)
    while True:
        job_id = await processor.process_batch()
        if args.once:
            return
        if job_id is None:
            await asyncio.sleep(max(0.25, args.poll_seconds))


if __name__ == "__main__":
    asyncio.run(run())
