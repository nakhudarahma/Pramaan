"""Create or verify a Pramaan administrator.

Usage (from the Backend directory):
    python -m scripts.create_admin
    python -m scripts.create_admin --email admin@college.edu --name "Registrar"

Credentials default to ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_NAME from the
environment. Passwords are never printed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings, load_dotenv_if_present  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.repositories import user_repository  # noqa: E402


def ensure_admin(
    *,
    email: str,
    password: str,
    full_name: str | None,
    department: str | None = None,
    is_superadmin: bool = True,
) -> str:
    """Create an admin, or return the id of an existing admin.

    Raises RuntimeError when the email belongs to a non-admin account so the
    script never silently escalates a student.
    """
    if len(password) < 8:
        raise RuntimeError("Admin password must be at least 8 characters")

    init_db()
    with SessionLocal() as db:
        existing = user_repository.get_by_email(db, email)
        if existing is not None:
            if existing.role != UserRole.ADMIN.value:
                raise RuntimeError(
                    f"{email} already exists with role '{existing.role}'; refusing to escalate"
                )
            return existing.id

        user = user_repository.create_admin(
            db,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            department=department,
            is_superadmin=is_superadmin,
        )
        db.commit()
        return user.id


def main() -> int:
    load_dotenv_if_present(str(ROOT / ".env"))
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Create a Pramaan administrator")
    parser.add_argument("--email", default=settings.admin_email)
    parser.add_argument("--password", default=settings.admin_password)
    parser.add_argument("--name", default=settings.admin_name)
    parser.add_argument("--department", default=None)
    parser.add_argument("--no-superadmin", action="store_true")
    args = parser.parse_args()

    if not args.email or not args.password:
        parser.error("ADMIN_EMAIL and ADMIN_PASSWORD (or --email/--password) are required")

    try:
        user_id = ensure_admin(
            email=args.email,
            password=args.password,
            full_name=args.name,
            department=args.department,
            is_superadmin=not args.no_superadmin,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"admin ready: {args.email} ({user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
