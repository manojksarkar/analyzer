#!/usr/bin/env python3
"""Create the SampleCppProject in the running mock-api.

Reads the payload from create-sample-project.json (same folder), signs in,
POSTs /projects, and prints the new project id. Standard library only.

Usage:
    python create-sample-project.py
    python create-sample-project.py --email bob@aspice.dev --base-url http://localhost:8000/api/v1
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

PAYLOAD_FILE = Path(__file__).with_name("create-sample-project.json")


def post_json(url: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000/api/v1")
    ap.add_argument("--email", default="admin@aspice.dev")
    ap.add_argument("--password", default="secret")
    args = ap.parse_args()

    payload = json.loads(PAYLOAD_FILE.read_text(encoding="utf-8"))

    try:
        signin = post_json(
            f"{args.base_url}/auth/signin",
            {"email": args.email, "password": args.password},
        )
        token = signin["access_token"]
        print(f"Signed in as {args.email}")

        resp = post_json(f"{args.base_url}/projects", payload, token=token)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Cannot reach {args.base_url} — is mock-api running? ({e.reason})",
              file=sys.stderr)
        return 1

    p = resp["project"]
    print("Created project:")
    print(f"  id      = {p['id']}")
    print(f"  name    = {p['name']}")
    print(f"  status  = {p['status']}")
    print(f"  my_role = {p['my_role']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
