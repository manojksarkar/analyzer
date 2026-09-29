"""A project's config file, in and out of the New Project wizard.

The command line onboards a project from a config file (`analyzer.py onboard --config`), the web
app from its wizard. This module is the bridge between the two:

* `preview` reads a config file and fills in as much of the wizard as the file allows -- the
  architecture, the build settings, the repository -- and says what it could not fill, and why.
* `to_config_text` writes a project back out as a config file, which the command line reads and
  the wizard imports again.

The format is the engine's own (`engine/config/config.defaults.json`), plus one optional block for
what only the web app needs; the engine ignores it:

    "project": {"name": "Brake ECU", "repository": "https://github.com/org/repo", "branch": "main",
                "defines": ["DEBUG=1"]}

An access token is never read from a file: config files get shared and committed.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import PurePosixPath
from typing import Any, Callable, Optional

FILLED, CHECK, SKIPPED = "filled", "check", "skipped"

_PROJECT_SECTIONS = ("clang", "views", "docx")      # carried into the project's build config
_SERVER_SECTIONS = ("llm", "ui", "db")              # the server's settings, never a project's
# Paths on the machine that wrote the file; the server uses its own. `macrosFile` is set by the
# server from the project's preprocessor definitions.
_MACHINE_CLANG_KEYS = ("llvmLibPath", "clangIncludePath", "macrosFile")
_TOKEN_KEYS = ("token", "accessToken", "access_token", "repoAccessToken", "repo_access_token")
_KNOWN = {"project", "layers", "cores", *_PROJECT_SECTIONS, *_SERVER_SECTIONS}
_TOKEN_MESSAGE = ("The access token in the file was not used: tokens are never read from a "
                  "file. Type it in step 1, and take it out of the file.")
_VIEW_LABELS = (("flowcharts", "flowcharts"), ("behaviourDiagram", "behaviour diagrams"),
                ("unitDiagrams", "unit diagrams"))


class ConfigError(ValueError):
    """The text is not a config file: not JSON (with comments), or not an object."""


def _engine() -> None:
    engine_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)


def parse(text: str) -> dict:
    """The config in `text`, read the way every reader in this repo reads one: JSON with `//` and
    `/* */` comments and trailing commas."""
    _engine()
    from core.config import _strip_json_comments, _strip_trailing_commas
    try:
        data = json.loads(_strip_trailing_commas(_strip_json_comments(text or "")))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"This is not a readable config file: {exc.msg} "
                          f"(line {exc.lineno}, column {exc.colno}).") from exc
    if not isinstance(data, dict):
        raise ConfigError("A config file is a JSON object -- { ... } -- at its top level.")
    return data


# ---------------------------------------------------------------------------
# Config file -> wizard draft
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    """A repo-relative path in one spelling: '/' separators, no './', no wrapping slashes."""
    p = str(path or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def _join(layer_path: str, rel: str) -> str:
    base, rel = _norm(layer_path), _norm(rel)
    return f"{base}/{rel}" if base and base != "." and rel else (rel or base)


class _RepoTree:
    """The repository's files and folders, to check the paths a config names."""

    def __init__(self, nodes: list):
        self.files: set = set()
        self.folders: set = set()

        def walk(ns: list) -> None:
            for n in ns or []:
                if n.get("type") == "folder":
                    self.folders.add(n["path"])
                    walk(n.get("children") or [])
                else:
                    self.files.add(n["path"])
        walk(nodes)
        self._folded = {p.casefold(): p for p in (*self.files, *self.folders)}

    def find(self, path: str) -> Optional[str]:
        """The repository's spelling of `path`, or None. A config written on Windows may spell a
        folder in another case than git stores it."""
        if path in self.files or path in self.folders:
            return path
        return self._folded.get(path.casefold())


def _is_machine_path(path: str) -> bool:
    return os.path.isabs(path) or bool(re.match(r"^[A-Za-z]:[\\/]", path)) or path.startswith("\\\\")


def preview(cfg: dict, *, tree_nodes: Optional[list] = None,
            read_file: Optional[Callable[[str], Optional[bytes]]] = None,
            store_file: Optional[Callable[[bytes, str, str], dict]] = None) -> dict:
    """Fill the wizard from `cfg` as far as it goes.

    With `tree_nodes` (the repository's tree, as `git_cli.list_tree` returns it) every path is
    checked against the repository, and a definitions or data-dictionary file the config names is
    read from it (`read_file`) and stored as an upload (`store_file`). Without them the paths are
    taken as written, and the files are left for the user to upload.

    Returns `{draft, expected_uploads, report, repository_checked}`; each report item is
    `{level: filled | check | skipped, text}`.
    """
    report: list = []

    def say(level: str, text: str) -> None:
        report.append({"level": level, "text": text})

    tree = _RepoTree(tree_nodes) if tree_nodes is not None else None
    draft: dict = {"name": None, "repo_url": None, "branch": None, "architecture_layers": [],
                   "definitions": None, "data_dictionary": None, "settings": {}}
    expected: dict = {"definitions": None, "data_dictionary": None}

    defines = _read_project(cfg.get("project"), draft, say)
    if any(k in cfg for k in _TOKEN_KEYS):
        say(SKIPPED, _TOKEN_MESSAGE)
    _read_layers(cfg, draft, tree, say)
    _read_cores(cfg, draft, expected, tree, read_file, store_file, say)
    if defines and draft["definitions"] is None and expected["definitions"] is None:
        draft["definitions"] = {"mode": "manual", "defines": defines}
        say(FILLED, f"Preprocessor definitions: {len(defines)} typed in (`project.defines`).")
    elif defines:
        say(SKIPPED, "`project.defines` was not used: the file also names a definitions file, "
                     "and a project has one or the other.")
    _read_settings(cfg, draft, say)
    for key in cfg:
        if key not in _KNOWN and key not in _TOKEN_KEYS and not str(key).startswith("_"):
            say(SKIPPED, f"`{key}` is not a config section, so it was not read.")
    return {"draft": draft, "expected_uploads": expected, "report": report,
            "repository_checked": tree is not None}


def _read_project(block: Any, draft: dict, say) -> list:
    """Name, repository and branch from the optional `project` block; returns its `defines`."""
    if block is None:
        return []
    if not isinstance(block, dict):
        say(SKIPPED, "`project` should be an object, so it was not read.")
        return []
    got = []
    for key, field in (("name", "name"), ("repository", "repo_url"), ("branch", "branch")):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            draft[field] = value.strip()
            got.append(key)
    if got:
        say(FILLED, f"Project: {', '.join(got)}.")
    if any(k in block for k in _TOKEN_KEYS):
        say(SKIPPED, _TOKEN_MESSAGE)
    raw = block.get("defines")
    return [str(d).strip() for d in raw if str(d).strip()] if isinstance(raw, list) else []


def _read_layers(cfg: dict, draft: dict, tree: Optional[_RepoTree], say) -> None:
    _engine()
    from core.config import validate_layer_names
    layers = cfg.get("layers")
    if not layers:
        say(CHECK, "The file has no `layers`, so the architecture is empty -- add it in step 3.")
        return
    if not isinstance(layers, dict):
        say(CHECK, "`layers` should be an object, so the architecture was not read.")
        return
    for problem in validate_layer_names(cfg):
        say(CHECK, problem)

    out: list = []
    n_groups = n_comps = 0
    missing: list = []
    for lname, lcfg in layers.items():
        if not isinstance(lcfg, dict):
            say(SKIPPED, f"Layer `{lname}` is not an object, so it was not read.")
            continue
        lpath = _norm(str(lcfg.get("path") or lname))
        if tree is not None and lpath and lpath != "." and tree.find(lpath) is None:
            missing.append(f"layer {lname}: `{lpath}`")
        groups = []
        for gname, comps in (lcfg.get("groups") or {}).items():
            if not isinstance(comps, dict):
                say(SKIPPED, f"{lname} / {gname}: its components should be an object, so it was not read.")
                continue
            components = []
            for cname, value in comps.items():
                rels = [value] if isinstance(value, str) else (
                    [v for v in value if isinstance(v, str)] if isinstance(value, list) else [])
                files: list = []
                absent: list = []
                for rel in rels:
                    full = _join(lpath, rel)
                    if not full:
                        continue
                    if tree is not None:
                        actual = tree.find(full)
                        if actual is None:
                            absent.append(f"`{full}`")
                            continue
                        full = actual
                    if full not in files:
                        files.append(full)
                if absent and not files:
                    # None of its paths exists: a component with no files would only produce an
                    # empty document, so it is left out rather than kept as a husk.
                    missing.append(f"{lname} / {gname} / {cname} (none of its paths: {', '.join(absent)})")
                    continue
                missing.extend(f"{lname} / {gname} / {cname}: {a}" for a in absent)
                components.append({"name": str(cname), "files": files})
            if comps and not components:
                continue                        # every component left out: so is the group
            n_comps += len(components)
            groups.append({"name": str(gname), "components": components})
        n_groups += len(groups)
        out.append({"name": str(lname), "path": lpath, "lib_paths": [], "groups": groups})

    draft["architecture_layers"] = out
    say(FILLED, f"Architecture: {len(out)} layer{'s' * (len(out) != 1)}, "
                f"{n_groups} group{'s' * (n_groups != 1)}, "
                f"{n_comps} component{'s' * (n_comps != 1)}.")
    if tree is None:
        say(CHECK, "Paths are checked against the repository once it is connected "
                   "(Test Connection).")
    for m in missing:
        say(CHECK, f"Not in the repository, so left out -- {m}.")


def _read_cores(cfg: dict, draft: dict, expected: dict, tree: Optional[_RepoTree],
                read_file, store_file, say) -> None:
    """The definitions and data dictionary of the core the layers use -- one core for now."""
    _engine()
    from core.config import core_source, get_layer_cores, validate_cores
    for problem in validate_cores(cfg):
        say(CHECK, problem)
    used: list = []
    for lname in (cfg.get("layers") or {}) if isinstance(cfg.get("layers"), dict) else ():
        for core in get_layer_cores(cfg, lname):
            if core not in used:
                used.append(core)
    if not used:
        if cfg.get("cores"):
            say(SKIPPED, "No layer uses a core (`layers.<name>.cores`), so the `cores` files were "
                         "not read.")
        return
    core = used[0]
    if len(used) > 1:
        say(SKIPPED, f"Only one core's files are used for now: {core}. Not read: "
                     f"{', '.join(used[1:])} -- every layer gets {core}'s definitions and data "
                     f"dictionary.")

    for key, kind, label, field in (
            ("macros", "preprocessor_definitions", "Preprocessor definitions", "definitions"),
            ("dataDictionary", "data_dictionary", "Data dictionary", "data_dictionary")):
        src = core_source(cfg, core, key)
        if not src:
            continue
        name = PurePosixPath(src.replace("\\", "/")).name
        upload = _from_repository(src, kind, tree, read_file, store_file)
        if isinstance(upload, str):                       # found, but not a usable file
            expected[field] = name
            say(CHECK, f"{label}: `{name}` is in the repository but could not be used -- {upload}")
        elif upload:
            entry = {"file_id": upload["id"], "file_name": upload["file_name"],
                     "size": upload["size"]}
            draft[field] = {"mode": "upload", **entry} if field == "definitions" else entry
            say(FILLED, f"{label}: `{name}`, read from the repository.")
        else:
            expected[field] = name
            if _is_machine_path(src):
                say(CHECK, f"{label}: upload `{name}` in step 2 -- `{src}` is a path on the "
                           f"machine that wrote the config.")
            elif tree is None:
                say(CHECK, f"{label}: `{name}` is read from the repository once it is connected "
                           f"(Test Connection), or upload it in step 2.")
            else:
                say(CHECK, f"{label}: upload `{name}` in step 2 -- the repository has no file "
                           f"`{_norm(src)}`.")
    if core_source(cfg, core, "compileCommands"):
        say(SKIPPED, f"`cores.{core}.compileCommands` (include paths from compile_commands.json) "
                     f"is not imported: the web app has no field for it yet. Add include folders "
                     f"per layer in step 3 (Lib Paths).")


def _from_repository(src: str, kind: str, tree: Optional[_RepoTree], read_file, store_file):
    """The file at `src` in the repository, stored as an upload: its record, an error message
    when it cannot be used, or None when it is not there to read."""
    if tree is None or read_file is None or store_file is None or _is_machine_path(src):
        return None
    actual = tree.find(_norm(src))
    if actual is None or actual not in tree.files:
        return None
    data = read_file(actual)
    if data is None:
        return "reading it failed (a file over 5 MB is not read)."
    try:
        return store_file(data, PurePosixPath(actual).name, kind)
    except ValueError as exc:
        return str(exc)


def _read_settings(cfg: dict, draft: dict, say) -> None:
    clang = cfg.get("clang")
    if isinstance(clang, dict):
        keep = {k: v for k, v in clang.items() if k not in _MACHINE_CLANG_KEYS}
        machine = [k for k in _MACHINE_CLANG_KEYS if k in clang]
        if keep:
            draft["settings"]["clang"] = keep
            args = keep.get("clangArgs")
            detail = f" ({' '.join(str(a) for a in args)})" if isinstance(args, list) and args else ""
            say(FILLED, f"Compiler settings: {', '.join(keep)}{detail}.")
        if machine:
            say(SKIPPED, f"clang.{', clang.'.join(machine)}: paths on the machine that wrote the "
                         f"file -- the server uses its own.")
    views = cfg.get("views")
    if isinstance(views, dict) and views:
        draft["settings"]["views"] = views
        on = [label for key, label in _VIEW_LABELS if views.get(key) is True]
        off = [label for key, label in _VIEW_LABELS if views.get(key) is False]
        parts = ([f"{', '.join(on)} on"] if on else []) + ([f"{', '.join(off)} off"] if off else [])
        say(FILLED, "Document views" + (f": {'; '.join(parts)}." if parts else "."))
    docx = cfg.get("docx")
    if isinstance(docx, dict) and docx:
        draft["settings"]["docx"] = docx
        say(FILLED, "Document settings (`docx`).")
    for section in _SERVER_SECTIONS:
        if section in cfg:
            say(SKIPPED, f"`{section}` is this server's setting, not the project's, so it was not "
                         f"read.")


# ---------------------------------------------------------------------------
# Project -> config file
# ---------------------------------------------------------------------------

def to_config_text(project: Any, today: Optional[datetime.date] = None) -> str:
    """The project as a config file (JSON with a comment header): what the command line needs to
    onboard it, and what the wizard imports again. Never the access token."""
    from .pipeline_runner import _convert_layers
    bc = project.build_config or {}
    layers = _convert_layers(project.architecture_layers or [])

    proj: dict = {"name": project.name}
    if project.repo_url:
        proj["repository"] = project.repo_url
    if project.default_branch:
        proj["branch"] = project.default_branch
    defs = bc.get("preprocessor_definitions") if isinstance(bc.get("preprocessor_definitions"), dict) else {}
    if defs.get("mode") == "manual" and defs.get("defines"):
        proj["defines"] = [str(d) for d in defs["defines"]]

    core: dict = {}
    if defs.get("mode") == "upload" and defs.get("file_name"):
        core["macros"] = defs["file_name"]
    dd = bc.get("data_dictionary")
    if isinstance(dd, dict) and dd.get("file_name"):
        core["dataDictionary"] = dd["file_name"]
    if core:
        for layer in layers.values():
            layer["cores"] = ["Core1"]

    cfg: dict = {"project": proj, "layers": layers}
    if core:
        cfg["cores"] = {"Core1": core}
    for section in _PROJECT_SECTIONS:
        if isinstance(bc.get(section), dict) and bc[section]:
            cfg[section] = bc[section]

    day = (today or datetime.date.today()).isoformat()
    header = [
        f'Config of the project "{project.name}", downloaded {day}.',
        'Import it in the New Project wizard ("Import config"), or onboard it from the command line:',
        "  python analyzer.py onboard --project-id <id> --source <repository> --config <this file>"
        " --branch <branch> --version-id v1 --commit <sha>",
        "`project` is read only by the web app. The access token is not included.",
    ]
    if core:
        header.append("`cores.Core1` names the files uploaded in the web app: put them next to this "
                      "file, or fix the paths, before using it from the command line.")
    return ("".join(f"// {h}\n" for h in header)
            + json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
