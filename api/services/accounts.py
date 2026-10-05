"""User accounts: create one, set its password.

Shared by the Team page's invite (`POST /projects/{id}/members/invite`, which creates the account of
an address that has none) and the command line (`analyzer.py user add|password|list`). Before this
nothing created an account: there was no sign-up and no admin route, so nobody but the seeded
logins could be added to a project.

Errors are `AccountError` with a code; the route turns them into HTTP answers, the CLI prints them.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

MIN_PASSWORD = 8
# no 0/O, 1/l/I: a temporary password is read aloud or copied by hand
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalise_email(email: Optional[str]) -> str:
    """An address as stored: trimmed, lower case. Refused unless it looks like one."""
    e = (email or "").strip().lower()
    if not _EMAIL.match(e):
        raise AccountError("INVALID_EMAIL", "%r is not an email address." % (email or ""))
    return e


def find_user(db: Any, email: str):
    """The account of `email`, matched as typed and then in lower case (stored addresses are)."""
    e = (email or "").strip()
    return db.users.get_by_email(e) or db.users.get_by_email(e.lower())


def initials_of(name: str) -> str:
    parts = [p for p in re.split(r"[\s._-]+", name or "") if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def temporary_password() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(12))


def check_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise AccountError("WEAK_PASSWORD", "A password needs at least %d characters." % MIN_PASSWORD)
    return password


def create_user(db: Any, email: str, name: Optional[str] = None,
                password: Optional[str] = None) -> Tuple[Any, Optional[str]]:
    """Create an account. Returns `(user, temporary_password)`; the second is None when the caller
    gave the password, else the one generated -- shown once, to be passed on and changed."""
    from ..middleware.auth import hash_password
    from ..models.domain import User

    address = normalise_email(email)
    if find_user(db, address) is not None:
        raise AccountError("USER_EXISTS", "An account already uses %s." % address)
    display = (name or "").strip() or " ".join(
        w.capitalize() for w in re.split(r"[._-]+", address.split("@")[0]) if w) or address
    temp = None
    if password is None:
        password = temp = temporary_password()
    check_password(password)
    user = User(id="u" + uuid.uuid4().hex[:10], email=address, name=display,
                initials=initials_of(display), avatar_url=None,
                hashed_password=hash_password(password), created_at=datetime.now(timezone.utc))
    db.users.create(user)
    return user, temp


def set_password(db: Any, user: Any, password: Optional[str] = None) -> Optional[str]:
    """Set a user's password; with none given, a temporary one, which is returned."""
    from ..middleware.auth import hash_password

    temp = None
    if password is None:
        password = temp = temporary_password()
    check_password(password)
    user.hashed_password = hash_password(password)
    db.users.update(user)
    return temp
