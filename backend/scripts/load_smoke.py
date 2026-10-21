from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass

import httpx


@dataclass(frozen=True)
class LoadResult:
    requests: int
    successes: int
    failures: int
    duration_seconds: float
    requests_per_second: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


async def run_load(
    url: str,
    *,
    requests: int,
    concurrency: int,
    token: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
) -> LoadResult:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    successes = 0
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = httpx.Timeout(15.0)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        async def execute() -> None:
            nonlocal successes
            async with semaphore:
                request_started = time.perf_counter()
                try:
                    response = await client.get(url, headers=headers)
                    if response.is_success:
                        successes += 1
                except httpx.HTTPError:
                    pass
                finally:
                    latencies.append((time.perf_counter() - request_started) * 1000)

        await asyncio.gather(*(execute() for _ in range(requests)))
    duration = time.perf_counter() - started
    return LoadResult(
        requests=requests,
        successes=successes,
        failures=requests - successes,
        duration_seconds=round(duration, 3),
        requests_per_second=round(requests / duration, 2) if duration else 0.0,
        p50_ms=round(percentile(latencies, 0.50), 2),
        p95_ms=round(percentile(latencies, 0.95), 2),
        p99_ms=round(percentile(latencies, 0.99), 2),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded HTTP load and latency certification smoke test.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health/live")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--token", default="")
    parser.add_argument("--max-p95-ms", type=float, default=2000)
    parser.add_argument("--min-success-rate", type=float, default=0.99)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.requests <= 100_000:
        raise SystemExit("--requests must be between 1 and 100000")
    if not 1 <= args.concurrency <= 1_000:
        raise SystemExit("--concurrency must be between 1 and 1000")
    result = asyncio.run(
        run_load(
            args.url,
            requests=args.requests,
            concurrency=args.concurrency,
            token=args.token,
        )
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    success_rate = result.successes / result.requests
    if success_rate < args.min_success_rate or result.p95_ms > args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
