from __future__ import annotations

import argparse
import asyncio

from app.db import AsyncSessionLocal
from app.services.outbox import OutboxProcessor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process durable vector-indexing outbox events.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser.parse_args()


async def run(once: bool, poll_seconds: float) -> None:
    processor = OutboxProcessor(AsyncSessionLocal)
    while True:
        processed = await processor.process_batch()
        if once:
            print(f"claimed={processed}")
            return
        if processed == 0:
            await asyncio.sleep(max(0.1, poll_seconds))


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.once, args.poll_seconds))


if __name__ == "__main__":
    main()
