from __future__ import annotations

import argparse
import asyncio

from app.db import AsyncSessionLocal
from app.services.jira_sync import IntegrationScheduleProcessor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run due durable integration synchronization schedules.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    return parser.parse_args()


async def run(once: bool, poll_seconds: float) -> None:
    processor = IntegrationScheduleProcessor(AsyncSessionLocal)
    while True:
        processed = await processor.process_one()
        if once:
            print(f"processed={processed}")
            return
        if processed is None:
            await asyncio.sleep(max(1.0, poll_seconds))


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.once, args.poll_seconds))


if __name__ == "__main__":
    main()
