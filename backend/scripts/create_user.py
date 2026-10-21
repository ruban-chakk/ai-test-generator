from __future__ import annotations

import argparse
import asyncio
import getpass
import uuid

from sqlalchemy import func, or_, select

from app.core.security import GLOBAL_ROLES, hash_password
from app.db import AsyncSessionLocal
from app.models import AuditLog, Project, ProjectMembership, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an authenticated AI Test Generator user.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=sorted(GLOBAL_ROLES), default="reviewer")
    parser.add_argument("--project-id", type=uuid.UUID)
    parser.add_argument("--project-role", choices=sorted(GLOBAL_ROLES), default="reviewer")
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Replace credentials and revoke sessions when the username or email already exists.",
    )
    return parser.parse_args()


async def create_user(args: argparse.Namespace, raw_password: str) -> None:
    username = args.username.strip()
    email = args.email.strip().lower()
    if not username or not email:
        raise ValueError("username and email are required")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                or_(func.lower(User.username) == username.lower(), func.lower(User.email) == email)
            )
        )
        user = result.scalars().first()
        action = "user_created"
        if user and not args.reset_existing:
            raise ValueError("user already exists; pass --reset-existing to rotate credentials")
        if user:
            action = "user_credentials_reset"
            user.username = username
            user.email = email
            user.role = args.role
            user.password_hash = hash_password(raw_password)
            user.active = True
            user.token_version += 1
        else:
            user = User(
                username=username,
                email=email,
                role=args.role,
                password_hash=hash_password(raw_password),
                active=True,
            )
            db.add(user)
            await db.flush()

        if args.project_id:
            project = await db.get(Project, args.project_id)
            if not project:
                raise ValueError("project not found")
            membership_result = await db.execute(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == args.project_id,
                    ProjectMembership.user_id == user.id,
                )
            )
            membership = membership_result.scalars().first()
            if membership:
                membership.role = args.project_role
            else:
                db.add(
                    ProjectMembership(
                        project_id=args.project_id,
                        user_id=user.id,
                        role=args.project_role,
                    )
                )

        db.add(
            AuditLog(
                entity_type="user",
                entity_id=user.id,
                action=action,
                actor="bootstrap-cli",
                details={"role": args.role, "project_id": str(args.project_id) if args.project_id else None},
            )
        )
        await db.commit()
        print(f"{action}: {user.username} ({user.id})")


def main() -> None:
    args = parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    asyncio.run(create_user(args, password))


if __name__ == "__main__":
    main()
