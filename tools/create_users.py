"""Create user accounts in the database -- several at once -- and, optionally, add them to a project.

For development and demos: nothing in the product signs a person up, so a fresh database has only
`admin@aspice.dev`. This makes the people a review needs, ready to assign.

    # the default team -- admin@aspice.dev as the admin, dev1..dev5@aspice.dev (password demo1234)
    python tools/create_users.py
    python tools/create_users.py --project-id pfc66bf4b        # ... and add them to a project

    # your own people: one, or a CSV with a header  email,name[,password][,role]
    # (a sample to copy: tools/team.example.csv; an empty password = a temporary one, printed)
    python tools/create_users.py --email bob@company.com --name "Bob Kumar" --project-id P
    python tools/create_users.py --file team.csv --project-id P --role developer

Safe to run again: an account that exists is left as it is (`--reset` sets its password again) and a
membership that exists is made active with the role given. Without `--password` the demo team gets
`demo1234` and anyone else a temporary password; every password set is printed once.

The database is the one the engine and the API use: `DATABASE_URL`, else the `db` section of
`engine/config/config.local.json`. One person at a time: `python analyzer.py user add`.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine"), os.path.join(_ROOT, "tools")]

ROLES = ("admin", "developer", "reviewer")
DEMO_PASSWORD = "demo1234"
DEMO_TEAM = [
    # (email, name, role). admin@aspice.dev is the API's default login (api/main.py), so it
    # usually exists and keeps its password; it assigns and approves.
    ("admin@aspice.dev", "Administrator", "admin"),
    *[(f"dev{i}@aspice.dev", f"Developer {i}", "developer") for i in range(1, 6)],
]


def create_users(db, people, *, project_id=None, role="developer", password=None, reset=False):
    """`people`: [(email, name, password or None, role or None)]. Returns one row per person:
    (email, name, password set or None, "created" | "exists" | "reset", membership or None)."""
    from api.services import accounts
    from grant_access import grant

    rows = []
    for email, name, own_password, own_role in people:
        pw = own_password or password
        user = accounts.find_user(db, email)
        if user is None:
            user, temp = accounts.create_user(db, email, name, pw)
            what, shown = "created", (temp or pw)
        elif reset:
            temp = accounts.set_password(db, user, pw)
            what, shown = "reset", (temp or pw)
        else:
            what, shown = "exists", None
        membership = None
        if project_id:
            with db._engine.begin() as cx:
                membership = grant(cx, project_id, user.id, own_role or role)
        rows.append((user.email, user.name, shown, what, membership))
    return rows


def _read_file(path):
    people = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, rec in enumerate(csv.DictReader(fh), start=2):
            email = (rec.get("email") or "").strip()
            if not email:
                continue
            role = (rec.get("role") or "").strip() or None
            if role and role not in ROLES:
                raise SystemExit(f"{path}:{i}: role {role!r} is not one of {', '.join(ROLES)}")
            people.append((email, (rec.get("name") or "").strip() or None,
                           (rec.get("password") or "").strip() or None, role))
    return people


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true",
                     help="the default team: admin@aspice.dev + dev1..dev5@aspice.dev "
                          "(what no --file or --email does)")
    src.add_argument("--file", help="CSV with a header: email,name[,password][,role]")
    src.add_argument("--email", help="one person")
    ap.add_argument("--name", help="with --email: the person's name (default: from the address)")
    ap.add_argument("--password", help="the password for everyone created (default: demo1234 for "
                                       "the default team, else a temporary one each)")
    ap.add_argument("--project-id", help="also add everyone to this project, as an active member")
    ap.add_argument("--role", default="developer", choices=ROLES,
                    help="their role in --project-id when the list gives none (default developer)")
    ap.add_argument("--reset", action="store_true", help="set the password of existing accounts again")
    args = ap.parse_args(argv)

    from core.db import is_database_configured
    if not is_database_configured():
        print("no database is configured (DATABASE_URL, or the db section of "
              "engine/config/config.local.json).", file=sys.stderr)
        return 2
    from api.db.postgres.database import SqlDatabase
    from api.services.accounts import AccountError
    db = SqlDatabase()

    if not (args.file or args.email):                   # the default: the demo team
        people = [(e, n, None, r) for e, n, r in DEMO_TEAM]
        password = args.password or DEMO_PASSWORD
    elif args.file:
        people, password = _read_file(args.file), args.password
    else:
        people, password = [(args.email, args.name, None, None)], args.password

    if args.project_id and db.projects.get(args.project_id) is None:
        print(f"no project {args.project_id!r}.", file=sys.stderr)
        return 2
    try:
        rows = create_users(db, people, project_id=args.project_id, role=args.role,
                            password=password, reset=args.reset)
    except AccountError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    width = max(len(r[0]) for r in rows)
    for email, name, shown, what, membership in rows:
        line = f"{email:<{width}}  {name:<22} {what:<8}"
        if shown:
            line += f" password: {shown}"
        if membership:
            line += f"   project {args.project_id}: {membership}"
        print(line)
    if any(r[2] for r in rows):
        print("\nPasswords are shown once. Each person can change theirs after signing in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
