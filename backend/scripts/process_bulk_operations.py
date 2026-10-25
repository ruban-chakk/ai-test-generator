import asyncio
import logging

from app.db import AsyncSessionLocal
from app.services.bulk_operations import BulkOperationProcessor


logging.basicConfig(level=logging.INFO)


async def main() -> None:
    processor = BulkOperationProcessor(AsyncSessionLocal)
    while True:
        job_id = await processor.process_batch()
        if job_id is None:
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
