from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def normalized_libpq_dsn(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def validate_drill_target(source_dsn: str, target_dsn: str) -> None:
    source = urlsplit(normalized_libpq_dsn(source_dsn))
    target = urlsplit(normalized_libpq_dsn(target_dsn))
    if source == target:
        raise ValueError("Recovery target must differ from the source database")
    target_database = target.path.lstrip("/")
    if not target_database.endswith("_drill"):
        raise ValueError("Recovery target database name must end in _drill")
    if target.hostname not in {"127.0.0.1", "localhost", "postgres"}:
        raise ValueError("Recovery drill target must be an explicitly isolated local host")


def redacted_dsn(value: str) -> str:
    parsed = urlsplit(normalized_libpq_dsn(value))
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    if parsed.username:
        host = f"{parsed.username}:***@{host}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def run_command(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def is_known_transaction_timeout_warning(stderr: str) -> bool:
    return (
        stderr.count("pg_restore: error:") == 1
        and 'unrecognized configuration parameter "transaction_timeout"' in stderr
        and "errors ignored on restore: 1" in stderr
    )


def restore_dump(target: str, dump_path: Path) -> str | None:
    completed = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", target, str(dump_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return None
    if is_known_transaction_timeout_warning(completed.stderr):
        # Newer pg_dump clients emit this SET for older PostgreSQL servers. The server rejects only that
        # session setting; structural verification below still gates the restored database.
        return "client emitted unsupported transaction_timeout session setting"
    raise RuntimeError(f"pg_restore failed with exit code {completed.returncode}")


def run_drill(source_dsn: str, target_dsn: str) -> dict:
    validate_drill_target(source_dsn, target_dsn)
    source = normalized_libpq_dsn(source_dsn)
    target = normalized_libpq_dsn(target_dsn)
    with tempfile.TemporaryDirectory(prefix="ai-test-generator-dr-") as temp_dir:
        dump_path = Path(temp_dir) / "backup.dump"
        started = time.perf_counter()
        run_command(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump_path), source])
        backup_seconds = time.perf_counter() - started
        dump_sha256 = hashlib.sha256(dump_path.read_bytes()).hexdigest()
        restore_started = time.perf_counter()
        compatibility_warning = restore_dump(target, dump_path)
        restore_seconds = time.perf_counter() - restore_started
        table_count = int(
            run_command([
                "psql", target, "-Atc",
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';",
            ])
        )
        migration = run_command(["psql", target, "-Atc", "SELECT version_num FROM alembic_version;"])
        if table_count < 10 or not migration:
            raise RuntimeError("Restored database failed structural verification")
        return {
            "source": redacted_dsn(source),
            "target": redacted_dsn(target),
            "dump_sha256": dump_sha256,
            "backup_seconds": round(backup_seconds, 3),
            "restore_seconds": round(restore_seconds, 3),
            "restored_table_count": table_count,
            "alembic_version": migration,
            "compatibility_warning": compatibility_warning,
            "status": "verified",
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup/restore drill into an isolated disposable PostgreSQL database.")
    parser.add_argument("--allow-target-reset", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.allow_target_reset:
        raise SystemExit("Pass --allow-target-reset to acknowledge that the isolated target is replaced")
    source = os.getenv("DR_SOURCE_DSN", "")
    target = os.getenv("DR_TARGET_DSN", "")
    if not source or not target:
        raise SystemExit("DR_SOURCE_DSN and DR_TARGET_DSN are required")
    print(json.dumps(run_drill(source, target), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
