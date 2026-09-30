#!/usr/bin/env python3
"""copy_changes.py - copy this repo's changes into another project folder, deletions included.

    python tools/copy_changes.py <target> --from <commit>    # first time: the commit the target has
    python tools/copy_changes.py <target>                    # later: from where the last copy stopped
    python tools/copy_changes.py <target> --dry-run          # show what it would do, change nothing

It replaces `git diff --name-only <commit> | xargs -I{} cp --parents {} <target>`, which never
removes a file the new code deleted or moved. A page moved into a folder
(pages/NewProjectPage.tsx -> pages/NewProjectPage/index.tsx) then leaves the old file in the
target. Vite loads the FILE, so the old UI shows although every new file was copied.

For <from>..HEAD (with --uncommitted: <from>..the working tree) it:
  - copies added and changed files, deletes deleted ones (a move is a delete plus an add), and
    removes the folders that leaves empty
  - backs up every file it overwrites or deletes to <target>/.copy-changes-backup/<time>/
  - writes the commit it copied up to into <target>/.copy-changes.json (the next run's --from)
  - checks the target for an old file that still hides a folder (from an earlier copy), and
    moves it to the backup when this repo no longer has it
  - says what to run next: npm install, pip install, analyzer.py setup, a restart
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_NAME = ".copy-changes.json"
BACKUP_NAME = ".copy-changes-backup"


def git(*args: str) -> str:
    p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n"
                         f"{p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8", "replace")


def parse_name_status(z: str) -> list[tuple[str, str]]:
    """`git diff --no-renames --name-status -z` output -> [(A|M|D|T, path)]."""
    parts = z.split("\0")
    return [(parts[i][:1], parts[i + 1]) for i in range(0, len(parts) - 1, 2) if parts[i]]


def remove_empty_dirs(start: Path, stop: Path) -> None:
    """Remove `start` and its parents up to (not including) `stop` while they are empty. A folder
    holding only __pycache__ counts as empty - Python rebuilds it."""
    d = start
    while d != stop and stop in d.parents:
        try:
            rest = [p for p in d.iterdir() if p.name != "__pycache__"]
            if rest:
                return
            shutil.rmtree(d)
        except OSError:
            return
        d = d.parent


def confirm(question: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        print(f"{question} - no terminal to ask; rerun with -y")
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def fix_hiding(target: Path, back_up, dry: bool) -> None:
    """An old file from an EARLIER copy can still hide a folder (pages/X.tsx beside pages/X/).
    When this repo no longer has that file it is stale for certain: move it to the backup."""
    sys.path.insert(0, str(ROOT / "tools"))
    from start_app import find_py_shadows, find_web_shadows
    hiding = find_web_shadows(target / "web-app" / "src")
    hiding += find_py_shadows([target / "api", target / "engine"])
    for stale, partner in hiding:
        rel, prel = stale.relative_to(target).as_posix(), partner.relative_to(target).as_posix()
        if (ROOT / rel).exists():
            print(f"!! {rel} hides {prel}, and this repo has both - check which one is right")
        elif dry:
            print(f"Would move to the backup: {rel} - an old copy that hides {prel}")
        else:
            back_up(stale, move=True)
            print(f"Moved to the backup: {rel} - an old copy that hid {prel} "
                  "(this repo no longer has it)")


def main(argv: list | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")                 # type: ignore[attr-defined]
    except Exception:                                           # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="copy_changes", description=__doc__.split("\n\n")[0],
                                 epilog=__doc__.split("\n\n", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="the other project's folder")
    ap.add_argument("--from", dest="base", metavar="COMMIT",
                    help="the commit the target already has (default: where the last copy stopped)")
    ap.add_argument("--uncommitted", action="store_true",
                    help="copy files as they are in this working tree, uncommitted changes included "
                         "(untracked files are never copied)")
    ap.add_argument("paths", nargs="*", help="only these paths (e.g. web-app api engine tools)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask before changing the target")
    ap.add_argument("--force", action="store_true",
                    help="copy into a folder that does not look like a copy of this project")
    args = ap.parse_args(argv)

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"Not a folder: {target}")
        return 1
    if target == ROOT or ROOT in target.parents or target in ROOT.parents:
        print(f"The target must be another project, not this repo or a folder around it: {target}")
        return 1

    state_file = target / STATE_NAME
    state = {}
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except ValueError:
            pass
    base = args.base or state.get("to")
    if not base:
        print("First copy into this folder: say which commit it already has, e.g.\n"
              f"    python tools/copy_changes.py {args.target} --from <commit>")
        return 1
    p = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet",
                        f"{base}^{{commit}}"], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"This repo has no commit {base!r}" + (" (from the last copy - was the branch "
              "rebased?)" if not args.base else "") + ". Pass --from <commit>.")
        return 1
    base_sha = p.stdout.strip()
    head_sha = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    upto = "the working tree" if args.uncommitted else f"{branch} @ {head_sha[:7]}"

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = target / BACKUP_NAME / stamp

    def back_up(p: Path, move: bool) -> None:
        dest = backup / p.relative_to(target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(p), str(dest))
        elif p.is_file():
            shutil.copy2(p, dest)

    def record(copied: int, deleted: int) -> None:
        """Where this copy stopped - the next run's --from."""
        state_file.write_text(json.dumps({
            "source": str(ROOT), "branch": branch, "from": base_sha,
            "to": head_sha,              # with --uncommitted the next run re-copies what's past HEAD
            "uncommitted": args.uncommitted,
            "copied_at": dt.datetime.now().isoformat(timespec="seconds"),
            "copied": copied, "deleted": deleted,
        }, indent=2), encoding="utf-8")

    diff = ["diff", "--no-renames", "--name-status", "-z", base_sha]
    if not args.uncommitted:
        diff.append("HEAD")
    changes = parse_name_status(git(*diff, "--", *args.paths))
    copies = [p for s, p in changes if s != "D"]
    deletes = [p for s, p in changes if s == "D"]
    print(f"From  {ROOT}\nTo    {target}\nRange {base_sha[:7]} -> {upto}"
          + (f"   (from the last copy, {state.get('copied_at', '?')})" if not args.base else ""))
    if not changes:
        print("\nNothing changed in that range.")
        fix_hiding(target, back_up, dry=args.dry_run)
        if not args.dry_run:
            record(0, 0)
        return 0

    # The files are copied from this working tree, so without --uncommitted they must BE the
    # committed version.
    if not args.uncommitted:
        dirty = set(filter(None, git("diff", "--name-only", "-z", "HEAD").split("\0")))
        dirty &= set(copies)
        if dirty:
            print(f"\n{len(dirty)} file(s) to copy have uncommitted changes here:")
            for p in sorted(dirty)[:10]:
                print(f"  {p}")
            print("Commit them, or pass --uncommitted to copy them as they are.")
            return 1

    tops = {p.split("/", 1)[0] for p in copies + deletes if "/" in p}
    if tops and not any((target / t).is_dir() for t in tops) and not args.force:
        print(f"\n{target} has none of {', '.join(sorted(tops))} - it does not look like a copy of "
              "this project. Check the folder, or pass --force.")
        return 1

    by_top: dict = {}
    for p in copies:
        top = p.split("/", 1)[0] if "/" in p else "(root)"
        by_top[top] = by_top.get(top, 0) + 1
    print(f"\nCopy   {len(copies)} file(s): "
          + ", ".join(f"{k} {v}" for k, v in sorted(by_top.items())))
    print(f"Delete {len(deletes)} file(s)" + (":" if deletes else ""))
    for p in deletes:
        print(f"  {p}" + ("" if (target / p).exists() else "   (already gone)"))
    if args.dry_run:
        fix_hiding(target, back_up, dry=True)
        print("\n--dry-run: nothing changed.")
        return 0
    if not args.yes and not confirm("\nChange the target?"):
        print("Nothing changed.")
        return 1

    deleted = 0
    for rel in deletes:                  # first: a deleted file may be where a folder now goes
        tp = target / rel
        if tp.is_file():
            back_up(tp, move=True)
            deleted += 1
            remove_empty_dirs(tp.parent, target)
    copied, missing = 0, []
    for rel in copies:
        src, tp = ROOT / rel, target / rel
        if not src.is_file():
            missing.append(rel)
            continue
        if tp.is_dir():                  # a folder where a file now goes
            back_up(tp, move=True)
        elif tp.exists():
            back_up(tp, move=False)
        tp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, tp)             # a fresh mtime, so no cache mistakes it for the old file
        copied += 1
    print(f"\nCopied {copied}, deleted {deleted}."
          + (f" Backup of what was replaced: {backup}" if backup.exists() else ""))
    for rel in missing:
        print(f"  not copied (missing here): {rel}")

    fix_hiding(target, back_up, dry=False)
    record(copied, deleted)

    changed = copies + deletes
    steps = []
    if any(p in ("web-app/package.json", "web-app/package-lock.json") for p in changed):
        steps.append("cd web-app && npm install        (web-app packages changed)")
    if any(p in ("package.json", "package-lock.json") for p in changed):
        steps.append("npm install                      (repo-root packages changed)")
    if "requirements.txt" in changed:
        steps.append("pip install -r requirements.txt  (Python packages changed)")
    if any(p.startswith("alembic/") or p == "api/db/postgres/schema.py" for p in changed):
        steps.append("python analyzer.py setup         (database schema changed)")
    if any(p.startswith(("api/", "engine/", "web-app/")) for p in changed):
        steps.append("restart the API and the web app  (start-app does it, installs included)"
                     if (target / "tools" / "start_app.py").is_file()
                     else "restart the API and the web app")
    if steps:
        print("\nNext, in " + str(target) + ":")
        for s in steps:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
