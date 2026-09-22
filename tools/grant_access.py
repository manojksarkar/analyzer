"""Give a user access to a project — the `project_members` row the API authorises against.

Why this exists
---------------
There are two front doors, and only one of them ever created a membership.

`POST /api/v1/projects` adds the creator as an admin member, because it knows who is logged in.
`analyzer.py onboard` has no logged-in user, so it created the `projects` row and stopped. The
result is a project that generates documents perfectly from the CLI and is **invisible over
HTTP**: `GET /projects` lists only what you are a member of, so it comes back `[]`, and every
`/projects/{id}/...` route answers

    403  {"code": "FORBIDDEN", "message": "Project membership required."}

Being "the admin" does not help, and that is not a bug in the check. There is no global role in
this system at all — `User` has no role field. `admin@aspice.dev` is a seeded LOGIN, not a
superuser. Authorisation is per project, via this table, and a project nobody was added to has
nobody who can read it.

`GET /projects/search` works on those projects because it does not filter by membership, which is
how they are findable at all while this row is missing.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

ROLES = ("admin", "developer", "reviewer")


def grant(cx, project_id: str, user_id: str, role: str = "admin",
          now: datetime.datetime | None = None) -> str:
    """Add or update one membership. Returns "created" | "updated" | "unchanged".

    Idempotent, because the obvious thing to do when an endpoint still says 403 is to run the
    command again, and a second row for the same pair would make `get_member` ambiguous.
    """
    import sqlalchemy as sa
    from api.db.postgres import schema as s

    now = now or datetime.datetime.now(datetime.timezone.utc)
    m = s.project_members
    row = cx.execute(sa.select(m.c.id, m.c.role, m.c.status)
                     .where(m.c.project_id == project_id, m.c.user_id == user_id)).first()
    if row is None:
        cx.execute(sa.insert(m), {
            "id": "m" + uuid.uuid4().hex[:8], "project_id": project_id, "user_id": user_id,
            "role": role, "status": "active", "invited_by": user_id,
            "invited_at": now, "joined_at": now})
        return "created"
    if (row.role, row.status) == (role, "active"):
        return "unchanged"
    # A membership that exists but is not `active` fails the check exactly like a missing one,
    # and "it says I am a member but I get 403" is worse to debug than "I am not a member".
    cx.execute(sa.update(m).where(m.c.id == row.id).values(role=role, status="active"))
    return "updated"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="grant_access.py",
        description="Give a user access to a CLI-onboarded project so the API will serve it.")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--email", help="the user to add (default: every user, when --all is given)")
    ap.add_argument("--all", action="store_true",
                    help="add EVERY user in the database. For a single-team internal instance "
                         "where the membership table is bookkeeping rather than a boundary.")
    ap.add_argument("--role", default="admin", choices=ROLES)
    args = ap.parse_args(argv)

    if not args.email and not args.all:
        ap.error("pass --email <address>, or --all to add every user")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from core.db import database_url, get_engine, require_database, _redact, DatabaseUnavailable

    try:
        require_database()
    except DatabaseUnavailable as exc:
        print(exc)
        print("\nRun `python analyzer.py setup` first.")
        return 2

    eng = get_engine()
    print(f"database : {_redact(database_url())}")

    with eng.begin() as cx:
        if not cx.execute(sa.select(s.projects.c.id)
                          .where(s.projects.c.id == args.project_id)).first():
            print(f"\nNo project {args.project_id!r}.")
            print("  Projects that exist: %s" % ", ".join(
                r.id for r in cx.execute(sa.select(s.projects.c.id).limit(20))) or "(none)")
            return 2

        if args.all:
            users = cx.execute(sa.select(s.users.c.id, s.users.c.email)).fetchall()
        else:
            users = cx.execute(sa.select(s.users.c.id, s.users.c.email)
                               .where(s.users.c.email == args.email)).fetchall()
            if not users:
                print(f"\nNo user with email {args.email!r}.")
                print("  Users that exist: %s" % ", ".join(
                    r.email for r in cx.execute(sa.select(s.users.c.email).limit(20))) or "(none)")
                return 2

        for u in users:
            what = grant(cx, args.project_id, u.id, args.role)
            print(f"  {what:<9} {u.email}  ->  {args.project_id} ({args.role})")

    print("\nThe API will serve this project now. Check with:")
    print("  GET /api/v1/projects            (it should no longer be an empty list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
