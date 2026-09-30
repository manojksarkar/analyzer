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
                "defines": {"Core1": ["DEBUG=1"]}}

`defines` holds each core's typed definitions (the engine reads macros from files only). A plain
list - written before cores - is the one core `Core1` that every layer uses.

A core's files (macros, data dictionary, compile commands) are the user's own inputs, never part of
the repository, so their paths are not looked up anywhere: step 2 asks for each file, and a folder
picked there fills every one it holds.

An access token is never read from a file: config files get shared and committed.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import PurePosixPath
from typing import Any, Optional

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


def preview(cfg: dict, *, tree_nodes: Optional[list] = None) -> dict:
    """Fill the wizard from `cfg` as far as it goes.

    With `tree_nodes` (the repository's tree, as `git_cli.list_tree` returns it) every layer and
    component path is checked against the repository; without it they are taken as written.

    Returns `{draft, expected_uploads, report, repository_checked}`. `expected_uploads` holds, per
    core, the path the config names for each of its files, as written ('/' separators): step 2
    asks for the file by its name, and matches a picked folder on the path's end. Each report item
    is `{level: filled | check | skipped, text, topic}`. The topic - project, architecture, files,
    settings, other - says which part of the wizard an item is about: once the user has changed
    the architecture, the wizard keeps its architecture items and takes the rest from a new check.
    """
    report: list = []

    def say(level: str, text: str, topic: str = "other") -> None:
        report.append({"level": level, "text": text, "topic": topic})

    tree = _RepoTree(tree_nodes) if tree_nodes is not None else None
    draft: dict = {"name": None, "repo_url": None, "branch": None, "architecture_layers": [],
                   "cores": [], "settings": {}}
    expected: dict = {}                 # core -> {macros, data_dictionary, compile_commands}

    defines = _read_project(cfg.get("project"), draft, say)
    if any(k in cfg for k in _TOKEN_KEYS):
        say(SKIPPED, _TOKEN_MESSAGE, "project")
    _read_layers(cfg, draft, tree, lambda level, text: say(level, text, "architecture"))
    files = lambda level, text: say(level, text, "files")  # noqa: E731
    _read_cores(cfg, draft, expected, files)
    _apply_defines(defines, draft, expected, files)
    _read_settings(cfg, draft, lambda level, text: say(level, text, "settings"))
    for key in cfg:
        if key not in _KNOWN and key not in _TOKEN_KEYS and not str(key).startswith("_"):
            say(SKIPPED, f"`{key}` is not a config section, so it was not read.")
    return {"draft": draft, "expected_uploads": expected, "report": report,
            "repository_checked": tree is not None}


def _read_project(block: Any, draft: dict, say) -> Any:
    """Name, repository and branch from the optional `project` block; returns its `defines` as
    written - `{Core: [...]}`, or a list from a file made before cores."""
    if block is None:
        return None
    if not isinstance(block, dict):
        say(SKIPPED, "`project` should be an object, so it was not read.", "project")
        return None
    got = []
    for key, field in (("name", "name"), ("repository", "repo_url"), ("branch", "branch")):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            draft[field] = value.strip()
            got.append(key)
    if got:
        say(FILLED, f"Project: {', '.join(got)}.", "project")
    if any(k in block for k in _TOKEN_KEYS):
        say(SKIPPED, _TOKEN_MESSAGE, "project")
    return block.get("defines")


def _read_layers(cfg: dict, draft: dict, tree: Optional[_RepoTree], say) -> None:
    _engine()
    from core.config import get_layer_cores, validate_layer_names
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
        if tree is not None and lpath and lpath != ".":
            actual = tree.find(lpath)
            if actual is None or actual not in tree.folders:
                # Every component path starts with it, so none of them can be there either.
                missing.append(f"layer {lname} (its path `{lpath}` is not a folder there)")
                continue
            lpath = actual
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
                    # None of its paths exists: a component with no files stops every run of the
                    # project before the parse, so it is left out rather than kept as a husk.
                    missing.append(f"{lname} / {gname} / {cname} (none of its paths: {', '.join(absent)})")
                    continue
                missing.extend(f"{lname} / {gname} / {cname}: {a}" for a in absent)
                components.append({"name": str(cname), "files": files})
            if comps and not components:
                continue                        # every component left out: so is the group
            n_comps += len(components)
            groups.append({"name": str(gname), "components": components})
        n_groups += len(groups)
        cores = get_layer_cores(cfg, lname)
        if len(cores) > 1:
            say(CHECK, f"Layer {lname} lists {len(cores)} cores; a layer is built for one, so it "
                       f"takes {cores[0]}.")
        out.append({"name": str(lname), "path": lpath, "lib_paths": [], "groups": groups,
                    "core": cores[0] if cores else None})

    draft["architecture_layers"] = out
    say(FILLED, f"Architecture: {len(out)} layer{'s' * (len(out) != 1)}, "
                f"{n_groups} group{'s' * (n_groups != 1)}, "
                f"{n_comps} component{'s' * (n_comps != 1)}.")
    if tree is None:
        say(CHECK, "Paths are checked against the repository once it is connected "
                   "(Test Connection).")
    for m in missing:
        say(CHECK, f"Not in the repository, so left out -- {m}.")


_CORE_INPUTS = (("macros", "macros"), ("dataDictionary", "data_dictionary"),
                ("compileCommands", "compile_commands"))


def _read_cores(cfg: dict, draft: dict, expected: dict, say) -> None:
    """Every core the config declares, and the path it names for each of the core's files -
    macros, data dictionary, compile commands - which step 2 asks for."""
    _engine()
    from core.config import validate_cores
    for problem in validate_cores(cfg):
        say(CHECK, problem)
    raw = cfg.get("cores")
    if raw is None:
        return
    if not isinstance(raw, dict):
        say(SKIPPED, "`cores` should be an object, so the cores were not read.")
        return
    names = [str(n) for n, c in raw.items() if isinstance(c, dict)]
    if names:
        say(FILLED, f"Cores: {', '.join(f'`{n}`' for n in names)} (step 2).")
    used = {l.get("core") for l in draft["architecture_layers"]}
    for name, ccfg in raw.items():
        name = str(name)
        if not isinstance(ccfg, dict):
            say(SKIPPED, f"`cores.{name}` should be an object, so it was not read.")
            continue
        core = {"name": name, "macros": None, "data_dictionary": None, "compile_commands": None}
        want = {"macros": None, "data_dictionary": None, "compile_commands": None}
        for key, field in _CORE_INPUTS:
            spec = ccfg.get(key)
            src = (spec.get("file") or spec.get("path")) if isinstance(spec, dict) else spec
            if isinstance(spec, dict) and spec.get("rootPrefix"):
                say(SKIPPED, f"`cores.{name}.{key}.rootPrefix` is not used: the prefix is worked "
                             f"out from the repository.")
            if isinstance(src, str) and src.strip():
                want[field] = src.strip().replace("\\", "/")
        named = [f"`{PurePosixPath(p).name}`" for p in want.values() if p]
        if named:
            say(CHECK, f"{name}: {', '.join(named)} - pick the folder that holds "
                       f"{'them' if len(named) > 1 else 'it'} in step 2, or upload each file there.")
        if name not in used:
            say(CHECK, f"{name}: no layer uses it (`layers.<name>.cores`) -- pick it for a layer "
                       f"in step 3.")
        draft["cores"].append(core)
        expected[name] = want


def _apply_defines(defines: Any, draft: dict, expected: dict, say) -> None:
    """`project.defines`: typed definitions per core - `{Core: [...]}`. A plain list, from a file
    written before cores, is the one core `Core1` that every layer uses."""
    if not defines:
        return

    def clean(lines: Any) -> list:
        return [str(d).strip() for d in lines if str(d).strip()] if isinstance(lines, list) else []

    if isinstance(defines, list):
        lines = clean(defines)
        if not lines:
            return
        if draft["cores"]:
            say(SKIPPED, "`project.defines` does not say which core its definitions are for; "
                         "write them as `project.defines.<Core>`.")
            return
        draft["cores"].append({"name": "Core1", "macros": {"mode": "manual", "defines": lines},
                               "data_dictionary": None, "compile_commands": None})
        expected["Core1"] = {"macros": None, "data_dictionary": None, "compile_commands": None}
        for layer in draft["architecture_layers"]:
            layer["core"] = layer.get("core") or "Core1"
        say(FILLED, f"Core1: {len(lines)} typed definitions (`project.defines`), used by every "
                    f"layer.")
        return
    if not isinstance(defines, dict):
        say(SKIPPED, "`project.defines` should be an object of cores, so it was not read.")
        return
    by_name = {c["name"]: c for c in draft["cores"]}
    for name, lines in defines.items():
        core = by_name.get(str(name))
        if core is None:
            say(SKIPPED, f"`project.defines.{name}`: `cores` has no core `{name}`, so it was not "
                         f"read.")
        elif core["macros"] or (expected.get(str(name)) or {}).get("macros"):
            say(SKIPPED, f"`project.defines.{name}` was not used: `cores.{name}.macros` names a "
                         f"file, and a core has one or the other.")
        elif clean(lines):
            core["macros"] = {"mode": "manual", "defines": clean(lines)}
            say(FILLED, f"{name}: {len(clean(lines))} typed definitions (`project.defines`).")


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
    from .project_cores import project_cores
    bc = project.build_config or {}
    layers = _convert_layers(project.architecture_layers or [])
    cores, layer_core = project_cores(bc, project.architecture_layers or [])
    for lname, core in layer_core.items():
        if core and lname in layers:
            layers[lname]["cores"] = [core]

    proj: dict = {"name": project.name}
    if project.repo_url:
        proj["repository"] = project.repo_url
    if project.default_branch:
        proj["branch"] = project.default_branch

    cores_cfg: dict = {}
    typed: dict = {}
    for c in cores:
        entry: dict = {}
        m = c["macros"]
        if m and m["mode"] == "upload" and m.get("file_name"):
            entry["macros"] = m["file_name"]
        elif m and m["mode"] == "manual":
            typed[c["name"]] = m["defines"]
        for key, field in (("dataDictionary", "data_dictionary"), ("compileCommands", "compile_commands")):
            if (c.get(field) or {}).get("file_name"):
                entry[key] = c[field]["file_name"]
        cores_cfg[c["name"]] = entry
    if typed:
        proj["defines"] = typed
    files = any(cores_cfg.values())

    cfg: dict = {"project": proj, "layers": layers}
    if cores_cfg:
        cfg["cores"] = cores_cfg
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
    if files:
        header.append("`cores` names the files uploaded in the web app by file name. For the "
                      "command line, write each one's path (absolute, or relative to the analyzer "
                      "folder); to import this file again, pick their folder in step 2.")
    if typed:
        header.append("`project.defines` holds each core's typed definitions; the command line "
                      "reads macros from a file (`cores.<Core>.macros`).")
    return ("".join(f"// {h}\n" for h in header)
            + json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
