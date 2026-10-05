"""A local repository: a git repository's folder on the server, as a project's repository.

The New Project wizard takes a Git URL or a local path. A local path is a folder on the machine
the API runs on, read with git like any remote (`git ls-remote <folder>`, `git clone <folder>`;
`incremental.clone` already knows git ignores --depth there), and it must BE a git repository:
a plain folder is refused. The wizard's Browse panel lists the server's folders one at a time
(`list_folders`): names only, and whether each is a git repository.

`repositories.localRoots` in engine/config/config.local.json -- a MACHINE setting, read like
`auth.accessTokenMinutes` -- limits both: the picker starts at those folders and cannot go above
them, and a local path outside them is refused. Empty or absent: every drive. A setting that
cannot be read allows nothing (it is a limit: failing open would lift it).
"""
from __future__ import annotations

import json
import os
import re
import string
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

# More than this many folders in one: the first ones by name, and `truncated`.
MAX_FOLDERS = 2000

# A remote: a scheme (https://, ssh://, git://) or scp-like `user@host:path`. Anything else the
# wizard sends is a local path; git would take a relative one against the API's own folder.
_REMOTE = re.compile(r"^[a-z][a-z0-9+.-]*://|^[\w.-]+@[\w.-]+:", re.IGNORECASE)


class LocalPathError(Exception):
    """A folder the picker cannot show: `status` 400 (not a full path), 403 (outside the allowed
    folders, or unreadable), 404 (no such folder)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _unquoted(text: str) -> str:
    # Explorer's "Copy as path" puts the path in double quotes.
    return (text or "").strip().strip('"').strip("'").strip()


def is_local(text: str) -> bool:
    """A local path (or a file:// link) rather than a remote's URL."""
    t = _unquoted(text)
    return bool(t) and (t.lower().startswith("file://") or not _REMOTE.match(t))


def clean(text: str) -> str:
    """The path as git and the picker use it: no quotes, a file:// link turned into its path,
    forward slashes."""
    p = _unquoted(text)
    if p.lower().startswith("file://"):
        p = unquote(p[len("file://"):])
        if re.match(r"^/[A-Za-z]:[\\/]", p):          # file:///D:/src -> D:/src
            p = p[1:]
    return p.replace("\\", "/")


def _norm(p: str) -> str:
    """Absolute, `..` resolved, forward slashes; a drive's root keeps its slash (`D:/`)."""
    q = os.path.normpath(p).replace("\\", "/")
    if re.fullmatch(r"[A-Za-z]:", q):
        q += "/"
    return q


def _key(p: str) -> str:
    """For comparing: links followed (a junction inside an allowed folder may point outside it),
    case folded where the file system folds it."""
    return os.path.normcase(os.path.realpath(p)).replace("\\", "/").rstrip("/")


def _inside(p: str, root: str) -> bool:
    k, r = _key(p), _key(root)
    return k == r or k.startswith(r + "/")


def _setting() -> Tuple[bool, Any]:
    """(read, `repositories.localRoots`) from engine/config/config.local.json. No file, section or
    key: (True, None)."""
    try:
        from ..db.session import _engine_on_path
        _engine_on_path()
        from core.paths import paths
        from core.config import _strip_json_comments, _strip_trailing_commas
        path = paths().config_local_path
        if not os.path.isfile(path):
            return True, None
        with open(path, encoding="utf-8") as fh:
            cfg = json.loads(_strip_trailing_commas(_strip_json_comments(fh.read()))) or {}
        return True, (cfg.get("repositories") or {}).get("localRoots")
    except Exception as exc:                                   # noqa: BLE001 - reported, allows nothing
        print(f"[api] could not read repositories.localRoots ({type(exc).__name__}: {exc}); "
              f"no local repository is allowed until it can be", file=sys.stderr)
        return False, None


def roots() -> Optional[List[str]]:
    """The folders local repositories are limited to; None: no limit. Read on every call, so a
    changed setting needs no restart."""
    ok, raw = _setting()
    if not ok:
        return []
    if raw is None or raw == []:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        print(f"[api] repositories.localRoots must be a list of folders, got {raw!r}; "
              f"no local repository is allowed until it is", file=sys.stderr)
        return []
    out = [_norm(clean(r)) for r in raw if isinstance(r, str) and r.strip()]
    return out or None


def _allowed(p: str, allowed: Optional[List[str]]) -> bool:
    return allowed is None or any(_inside(p, r) for r in allowed)


def _outside(p: str, allowed: List[str]) -> str:
    if not allowed:
        return (f"{p}: this server allows no local repository (its repositories.localRoots "
                f"setting lists none that can be read).")
    return f"{p} is outside the folders this server allows repositories in: {', '.join(allowed)}."


def is_git_repo(p: str) -> bool:
    """A work tree (it holds `.git`: a folder, or the file a worktree or a submodule has) or a
    bare repository (HEAD, objects/ and refs/ at its top)."""
    try:
        if os.path.exists(os.path.join(p, ".git")):
            return True
        return (os.path.isfile(os.path.join(p, "HEAD")) and os.path.isdir(os.path.join(p, "objects"))
                and os.path.isdir(os.path.join(p, "refs")))
    except OSError:
        return False


def problem(text: str) -> Optional[str]:
    """Why `text` cannot be a project's local repository; None when it can. Outside the allowed
    folders is said before whether the folder exists: the answer tells nothing about them."""
    p = clean(text)
    if not os.path.isabs(p):
        return ("Not a URL and not a full folder path: give the repository's URL (https://…) or "
                "its folder's full path on the server, e.g. D:/src/vcu-firmware.")
    p = _norm(p)
    allowed = roots()
    if not _allowed(p, allowed):
        return _outside(p, allowed or [])
    if not os.path.isdir(p):
        return f"No folder {p} on the server."
    if not is_git_repo(p):
        return f"{p} is not a git repository (it has no .git): pick the repository's root folder."
    return None


def _drives() -> List[str]:
    if os.name == "nt":
        return [f"{c}:/" for c in string.ascii_uppercase if os.path.isdir(f"{c}:/")]
    return ["/"]


def _join(parent: str, name: str) -> str:
    return parent.rstrip("/") + "/" + name if parent != "/" else "/" + name


def _parent(p: str, allowed: Optional[List[str]]) -> str:
    """The folder above `p`; "" for the top list (above a drive, or above an allowed folder)."""
    if allowed is not None and any(_key(p) == _key(r) for r in allowed):
        return ""
    up = _norm(os.path.dirname(p.rstrip("/")) or p)
    if _key(up) == _key(p) or not _allowed(up, allowed):
        return ""
    return up


def _entry(path: str) -> Dict[str, Any]:
    return {"name": path.rstrip("/").rsplit("/", 1)[-1] or path, "path": path, "git": is_git_repo(path)}


def list_folders(path: str = "") -> Dict[str, Any]:
    """One folder's folders, for the wizard's Browse panel: `{path, parent, folders: [{name,
    path, git}], limited, truncated}`. `path` "" is the top list: the allowed folders (named by
    their full path), else the server's drives (`/` off Windows); `parent` is null there and ""
    for "back to the top". Hidden folders (`.x`, `$x`) are left out. Raises `LocalPathError`."""
    allowed = roots()
    p = clean(path)
    if not p:
        tops = allowed if allowed is not None else _drives()
        folders = [dict(_entry(t), name=t) for t in tops if os.path.isdir(t)]
        return {"path": "", "parent": None, "folders": folders,
                "limited": allowed is not None, "truncated": False}
    if not os.path.isabs(p):
        raise LocalPathError(400, f"Give a folder's full path, e.g. D:/src (not {p}).")
    p = _norm(p)
    if not _allowed(p, allowed):
        raise LocalPathError(403, _outside(p, allowed or []))
    if not os.path.isdir(p):
        raise LocalPathError(404, f"No folder {p} on the server.")
    names: List[str] = []
    try:
        with os.scandir(p) as it:
            for e in it:
                if e.name.startswith((".", "$")):
                    continue
                try:
                    if e.is_dir():
                        names.append(e.name)
                except OSError:
                    continue
    except PermissionError:
        raise LocalPathError(403, f"The server cannot read {p}.")
    names.sort(key=str.lower)
    truncated = len(names) > MAX_FOLDERS
    folders = [_entry(_join(p, n)) for n in names[:MAX_FOLDERS]]
    return {"path": p, "parent": _parent(p, allowed), "folders": folders,
            "limited": allowed is not None, "truncated": truncated}
