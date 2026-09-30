"""Rich document render — builds the {cover, toc, sections, meta} payload
from real analyzer output under ``output/<group>/``.

The section hierarchy mirrors ``src/docx_exporter.py`` exactly:
  1 Introduction
    1.1 Purpose  /  1.2 Scope  /  1.3 Terms, Abbreviations and Definitions
  N ComponentName
    N.1 Static Design
      [container diagram]  [dependency diagram]  [component/unit table]
      N.1.1 UnitName
        N.1.1.1 unit header   (global vars / typedefs / enums / defines)
        N.1.1.2 unit interface (8-column interface table)
        N.1.1.3 UnitName-FuncName   (flowchart_table section)
        …
    N.2 Dynamic Behaviour
      N.2.1 UnitName - FuncName  (behavior_table section)
  M Code Metrics, Coding Rule, Test Coverage
  Appendix A Design Guideline

When no live output exists for a group, the caller (routes/documents.py)
falls back to a synthesised payload built from stored section bodies.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re as _re
from pathlib import Path
from typing import Any, Optional

from .settings import get_settings as _get_settings
_REPO_ROOT = _get_settings().repo_root
OUTPUT_ROOT = _REPO_ROOT / "output"
_log = logging.getLogger(__name__)

KEY_SEP = "|"
_INCLUDE_GUARD_RE = _re.compile(r"^_*[A-Z][A-Z0-9_]*(?:_H|_HPP)_*$")


# ── output dir lookup (path-traversal safe) ──────────────────────────────────

def commit_output_root(project_id: Optional[str], commit_sha: Optional[str],
                       version_id: Optional[str] = None) -> Optional[Path]:
    """A specific version's output dir. Prefers the version-keyed layout
    ``workspaces/<pid>/versions/<ver…>/output`` (08 step 3); falls back to the commit-addressed
    ``workspaces/<pid>/<commit[:16]>/output`` for pre-migration snapshots. None when absent. Pass
    the result to output_group_dir/resolve_asset/find_docx so a VERSION renders, not the
    latest shared run."""
    if not project_id:
        return None
    ws = _REPO_ROOT / "workspaces" / project_id
    if version_id:
        d = ws / "versions" / version_id / "output"
        if d.is_dir():
            return d
    if commit_sha:
        d = ws / commit_sha[:16] / "output"
        if d.is_dir():
            return d
    return None


def output_group_dir(group: Optional[str], output_root: Optional[Path] = None) -> Optional[Path]:
    """The output dir for ``group`` inside ``output_root`` — a version's commit-dir output (via
    commit_output_root) or the shared OUTPUT_ROOT by default — if it exists and is safely
    contained. Path-traversal safe."""
    root = (output_root or OUTPUT_ROOT)
    if not group or not root.is_dir():
        return None
    root = root.resolve()
    d = (root / group).resolve()
    if d.is_dir() and (d == root or root in d.parents):
        return d
    return None


def resolve_asset(group: Optional[str], asset_path: str,
                  output_root: Optional[Path] = None) -> Optional[Path]:
    """Resolve ``<group>/<asset_path>`` inside the (version's) output, or None if unsafe/absent."""
    base = output_group_dir(group, output_root)
    if not base:
        return None
    target = (base / asset_path).resolve()
    if target.is_file() and base in target.parents:
        return target
    return None


# The file each process's exporter writes into a component's output dir (engine group_planner).
DOCX_PREFIX = {"SWE.3": "software_detailed_design", "SWE.4": "software_unit_test_specification"}


def find_docx(group: Optional[str], output_root: Optional[Path] = None,
              process: str = "SWE.3") -> Optional[Path]:
    """Return the real DOCX path of ``process``'s document for ``group`` in the (version's)
    output if it exists. One component dir holds both documents of a run."""
    prefix = DOCX_PREFIX.get(process)
    if not group or not prefix:
        return None
    base = output_group_dir(group, output_root)
    if not base:
        return None
    p = base / f"{prefix}_{group}.docx"
    return p if p.is_file() else None


# ── small utilities ───────────────────────────────────────────────────────────

def _readable_label(name: str) -> str:
    """Convert an identifier like 'g_readWrite' into a human label (mirrors docx_exporter)."""
    if not name:
        return ""
    for prefix in ("g_", "s_", "t_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.replace("_", " ")
    if len(name.strip()) <= 2:
        return ""
    return name[:1].upper() + name[1:] if name else ""


def _safe_fn(name: str) -> str:
    """Filename-safe version of a function name (mirrors utils.safe_filename)."""
    name = name.replace(" ", "-")
    return _re.sub(r"[^\w\-.]", "_", name)


def scoped_name(full_name: str, class_name: str = "") -> str:
    """Class-qualified display name: MyClass::foo (mirrors utils.scoped_name).

    Namespaces are dropped. Falls back to the bare name when className is absent, so
    models parsed before className existed render as they did before.
    """
    base = ((full_name or "").split("::")[-1]).strip()
    cls = (class_name or "").strip()
    return f"{cls}::{base}" if cls and base else base


def _strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments + trailing commas from JSONC.

    String-aware: ``//`` and ``/*`` inside string literals (e.g. a URL like
    ``http://host``) are preserved — a naive regex strip corrupts such values
    and makes the whole config unparseable (silently falling back to {}).
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        c = text[i]
        if escape:
            result.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            result.append(c)
            i += 1
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if in_string:
            result.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            if text[i + 1] == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i + 1 < n and (text[i] != "*" or text[i + 1] != "/"):
                    i += 1
                i += 2
                continue
        result.append(c)
        i += 1
    # trailing commas
    return _re.sub(r",\s*([}\]])", r"\1", "".join(result))


# ── model / config loaders ────────────────────────────────────────────────────

def _as_description_list(value: Any) -> list:
    """Coerce a behaviour row's ``behaviorDescription`` to the LIST the API contract promises.

    The engine emits one entry per call, but an entry can be a plain string (a single-line
    description) rather than a list. ``value or []`` passed a non-empty string straight through,
    so the UI called ``.map()`` on a string and the whole document view crashed with
    "data.descriptionList.map is not a function". Normalising here — the API/UI boundary — keeps
    every consumer (document render, compare render, DOCX) on one shape."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v is not None]
    return []


def _load_model_json(model_dir: Path, name: str) -> dict:
    p = model_dir / f"{name}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_config() -> dict:
    """The engine's own config, for a render with no version config to go by: the defaults the
    engine starts from, then the machine's overrides. (`config.json` was the defaults' old name;
    reading only it and the local file left the Introduction as placeholders.)"""
    cfg: dict = {}
    for fname in ("config.defaults.json", "config.json", "config.local.json"):
        p = _REPO_ROOT / "engine" / "config" / fname
        if not p.exists():
            continue
        try:
            text = _strip_jsonc(p.read_text(encoding="utf-8"))
            chunk = json.loads(text)
            _deep_merge(cfg, chunk)
        except Exception:
            pass
    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _load_abbreviations(config: dict) -> dict:
    path = (config.get("llm") or {}).get("abbreviationsPath", "").strip()
    if not path:
        return {}
    full_path = Path(path) if Path(path).is_absolute() else _REPO_ROOT / path
    if not full_path.is_file():
        return {}
    result: dict = {}
    try:
        for line in full_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, _, v = line.partition(":")
            elif "=" in line:
                k, _, v = line.partition("=")
            else:
                continue
            k, v = k.strip(), v.strip()
            if k:
                result[k] = v
    except OSError:
        pass
    return result


# ── unit header table builder (model-only, no source file reads) ──────────────

def _view_json(output_reader, group_dir: Path, rel_name: str):
    """One view artifact as parsed JSON — Postgres FIRST, then disk (doc 09, C0).

    `version_output_files` has held every view file since PG-5a, but the rendered document —
    the main product surface — still read them off local disk, so the document depended on the
    machine that produced it. `rel_path` is relative to the OUTPUT root, so the group name is
    prepended: the reader keys rows as "<group>/interface_tables.json".

    Returns None when neither source has it, so callers keep their existing empty handling.
    """
    if output_reader is not None:
        txt = output_reader.read_text(f"{group_dir.name}/{rel_name}")
        if txt is not None:
            try:
                return json.loads(txt)
            except ValueError:
                pass                       # malformed in the DB -> fall through to disk
    p = group_dir / rel_name
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def _flowchart_id(ids: Optional[dict], stem: str, item: dict) -> None:
    """Record which flowchart a picture is, for the page's label editor: `functionKey` is the
    `flowchart_id` R7/R8 take, and only an entry with a stored graph (`cfg`) has labels to edit.
    Written under the same stem and name as the DOT, so the two agree about overloads."""
    if ids is None:
        return
    name = (item.get("name") or "").strip()
    if name:
        ids.setdefault(stem, {})[name] = {"flowchart_id": item.get("functionKey") or None,
                                          "editable": bool(item.get("cfg"))}


def _load_flowcharts(flowcharts_dir: Path, output_reader=None, group_dir: Path = None,
                     ids: Optional[dict] = None) -> dict:
    """{unit_prefix: {func_name: flowchart_str}} — Postgres first, then disk (doc 09, C0).

    Unlike the other two view artifacts this is a DIRECTORY of per-unit files, so there is no
    single path to ask for: the units are discovered from the reader's file list, then read
    individually. Falls back to the directory scan when the store has none for this group.
    ``ids``, when given, is filled with each chart's `flowchart_id` (`_flowchart_id`).
    """
    if output_reader is not None and group_dir is not None:
        prefix = f"{group_dir.name}/flowcharts/"
        try:
            names = [r for r in output_reader._pg_files() if r.startswith(prefix)
                     and r.endswith(".json") and not r.endswith("_summary.json")]
        except Exception:
            names = []
        if names:
            result: dict = {}
            for rel in names:
                stem = rel.rsplit("/", 1)[-1][:-len(".json")]
                txt = output_reader.read_text(rel)
                if not txt:
                    continue
                try:
                    arr = json.loads(txt)
                except ValueError:
                    continue
                if not isinstance(arr, list):
                    continue
                result[stem] = {}
                for item in arr:
                    name = (item.get("name") or "").strip()
                    flowchart = (item.get("flowchart") or "").strip()
                    if name and flowchart:
                        result[stem][name] = flowchart
                        _flowchart_id(ids, stem, item)
            if result:
                return result
    return _load_flowcharts_from_dir(flowcharts_dir, ids)


def _load_flowcharts_from_dir(flowcharts_dir: Path, ids: Optional[dict] = None) -> dict:
    """Return {unit_prefix: {func_name: mermaid_str}}."""
    result: dict = {}
    if not flowcharts_dir.is_dir():
        return result
    for p in flowcharts_dir.iterdir():
        if p.suffix != ".json":
            continue
        stem = p.stem
        try:
            arr = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(arr, list):
                continue
            result[stem] = {}
            for item in arr:
                name = (item.get("name") or "").strip()
                flowchart = (item.get("flowchart") or "").strip()
                if name and flowchart:
                    result[stem][name] = flowchart
                    _flowchart_id(ids, stem, item)
        except Exception:
            pass
    return result


def _flowchart_svg():
    """engine/core/flowchart_svg: the file name, box count and size limit the engine draws
    flowchart SVGs by -- one definition, so the web render never disagrees with the files."""
    import sys
    eng = str(_REPO_ROOT / "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    from core import flowchart_svg
    return flowchart_svg


def _find_flowchart(flowcharts_map: dict, unit_keys: tuple, func_keys: tuple):
    """(dot, unit_key, func_key) for the first unit/function spelling the map has, else None.
    Which spelling matched names the picture: the engine calls it <unit_key>_<func_key>.svg."""
    for func_key in func_keys:
        for unit_key in unit_keys:
            dot = (flowcharts_map.get(unit_key) or {}).get(func_key) if unit_key and func_key else None
            if dot:
                return dot, unit_key, func_key
    return None


def _flowchart_entry(group_dir: Path, found: tuple, label: str, asset_base: str,
                     ids: Optional[dict] = None) -> dict:
    """One flowchart in a function's table: its SVG, drawn by views/flowcharts on every run.

    The DOT itself is not sent -- a document can hold 500+ of them, some huge. The reader gets
    what it needs before the image loads: the size to reserve, the box count, and, with no
    picture, why not ("too_large" over the engine's limit, else "missing": not drawn for this
    run, or drawn from another DOT). ``source_hash`` lets Compare see a flowchart change.
    ``flowchart_id`` names the chart to the review routes (R7/R8), and ``editable`` says it
    has a stored graph whose labels a reviewer can correct.
    """
    dot, unit_key, func_key = found
    fs = _flowchart_svg()
    boxes = fs.count_dot_boxes(dot)
    ident = ((ids or {}).get(unit_key) or {}).get(func_key) or {}
    entry = {"label": label, "boxes": boxes, "image_url": None, "width": None, "height": None,
             "source_hash": hashlib.sha256(dot.encode("utf-8")).hexdigest()[:16],
             "flowchart_id": ident.get("flowchart_id"),
             "editable": bool(ident.get("flowchart_id") and ident.get("editable"))}
    if boxes > fs.FLOWCHART_SVG_MAX_BOXES:
        return {**entry, "status": "too_large"}
    name = fs.svg_file_name(unit_key, func_key)
    path = group_dir / "flowcharts" / name
    size = fs.svg_size_px(path) if fs.svg_file_key(path) == fs.svg_content_key(dot) else None
    if not size:
        return {**entry, "status": "missing"}
    return {**entry, "status": "drawn", "image_url": f"{asset_base}/flowcharts/{name}",
            "width": size[0], "height": size[1]}


def _load_behavior_diagrams(group_dir: Path, output_reader=None) -> dict:
    """Return the _docxRows dict from behaviour_diagrams/_behaviour_pngs.json."""
    doc = _view_json(output_reader, group_dir, "behaviour_diagrams/_behaviour_pngs.json")
    if doc is not None:
        return doc.get("_docxRows", {}) if isinstance(doc, dict) else {}
    p = group_dir / "behaviour_diagrams" / "_behaviour_pngs.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("_docxRows", {})
    except Exception:
        return {}


# ── review & update: the texts a reviewer can correct ────────────────────────

def _engine_on_path() -> None:
    import sys
    eng = str(_REPO_ROOT / "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)


def load_overrides(version: Any) -> dict:
    """{(slot_kind, slot_key): row} of the version's corrections, orphans included.

    One query (`review.override_service.overrides_for_version`), so the page can say which of
    its texts a reviewer corrected without a lookup per text (REQ-ST-05). Best effort: {} with
    no database or when the read fails -- every text then reads as the LLM's, which is what the
    page showed before corrections existed.
    """
    vid = getattr(version, "id", None)
    if not vid:
        return {}
    try:
        _engine_on_path()
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            return {}
        from review.override_service import overrides_for_version
        with get_engine().connect() as cx:
            return {(r.slot_kind, r.slot_key): r for r in overrides_for_version(cx, vid)}
    except Exception as exc:                                       # noqa: BLE001 - see docstring
        _log.warning("render: could not read the corrections of %s: %s", vid, exc)
        return {}


class _Slots:
    """The `slot` a page text carries, so the web reader can correct it in place.

    Its address comes from `review.slot` -- the server builds every key, the client only sends
    one back (REQ-ID-01) -- and its state from `review.catalog.slot_view`, the one shape every
    review route returns a slot in (camelCase, as those routes answer). ``text`` is the slot's
    own text, which is not always what the page prints: a cell falls back to a stand-in
    (the interface descriptions' join, "X input", "-") where the slot is empty.
    ``None`` for a text whose key cannot be built -- an empty part, or no review package.
    """

    def __init__(self, rows: dict):
        self._rows = rows
        try:
            _engine_on_path()
            from review import slot as slot_mod
            from review.catalog import slot_view
            from review.phase3_overrides import join_bullets
            self._slot, self._view, self._join = slot_mod, slot_view, join_bullets
        except Exception as exc:                                   # noqa: BLE001
            _log.warning("render: review package unavailable, no slots on the page: %s", exc)
            self._slot = None

    def _make(self, kind: str, build, text: Optional[str]) -> Optional[dict]:
        if self._slot is None:
            return None
        try:
            key = build()
        except Exception:                                          # noqa: BLE001 - SlotKeyError
            return None
        text = (text or "").strip()
        return self._view(kind, key, "" if text in ("-", "N/A") else text,
                          self._rows.get((kind, key)))

    def entity(self, kind: str, entity_key: Optional[str], text: Optional[str]) -> Optional[dict]:
        """description, behaviourInputName, behaviourOutputName, structDescription."""
        return self._make(kind, lambda: self._slot.for_entity(kind, entity_key or ""), text)

    def unit(self, unit_key: str, text: Optional[str]) -> Optional[dict]:
        return self._make("unitDescription", lambda: self._slot.for_unit(unit_key), text)

    def behaviour(self, function_id: Optional[str], caller_id: Optional[str],
                  bullets: list) -> Optional[dict]:
        """A Dynamic Behaviour row's bullets, one slot for the whole list (R6)."""
        if self._slot is None:
            return None
        return self._make("behaviourDescription",
                          lambda: self._slot.for_behaviour_row(function_id or "", caller_id or ""),
                          self._join(bullets))


# ── section helpers ───────────────────────────────────────────────────────────

def _sec(sid: str, number: str, title: str, level: int, *, type: str = "richtext",
         content: Any = None, table: Any = None, image_url: Any = None,
         mermaid: Any = None, children: Any = None,
         flowchart_table: Any = None, behavior_table: Any = None) -> dict:
    d: dict = {
        "id": sid, "number": number, "title": title, "level": level, "type": type,
        "content": content, "table": table, "image_url": image_url,
        "mermaid": mermaid, "children": children or [],
    }
    if flowchart_table is not None:
        d["flowchart_table"] = flowchart_table
    if behavior_table is not None:
        d["behavior_table"] = behavior_table
    return d


def _pngs(group_dir: Path, subdir: str, pred) -> list[str]:
    d = group_dir / subdir
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix == ".png" and pred(p.name))


def _diagram_sec(asset_base: str, group_dir: Path, subdir: str, fn: str,
                 sid: str, number: str, title: str, level: int, caption: str) -> dict:
    rel = f"{subdir}/{fn}"
    mmd = (group_dir / subdir / fn).with_suffix(".mmd")
    return _sec(
        sid, number, title, level, type="diagram", content=caption,
        image_url=f"{asset_base}/{rel}",
        mermaid=mmd.read_text(encoding="utf-8") if mmd.exists() else None,
    )


def _flatten_toc(sections: list[dict]) -> list[dict]:
    """Flatten nested sections into a TOC list; skip unnumbered (diagram/table) entries."""
    out: list[dict] = []
    for s in sections:
        if s.get("number"):
            out.append({"id": s["id"], "number": s["number"], "title": s["title"], "level": s["level"]})
        out.extend(_flatten_toc(s["children"]))
    return out


# ── interfaces table (8-column, mirrors docx_exporter) ───────────────────────

def _cell_trim(s: str, max_len: int) -> str:
    """docx_exporter's cell trim: cut to `max_len` with a trailing `...`."""
    s = (s or "").strip()
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _param_type_label(p: dict) -> str:
    """A parameter as `type name` (docx_exporter._param_type_label); type only with no name."""
    t, n = (p.get("type", "") or "").strip(), (p.get("name", "") or "").strip()
    return f"{t} {n}".strip() if n else t


def _interfaces_table_8col(ifaces: list, slots: Optional[_Slots] = None) -> dict:
    """The unit interface table - with only its header row when the unit has no interface, as
    the DOCX prints it. With ``slots``, ``cell_slots`` says which cell is a correctable text:
    the Information column, each function's or global's `description`."""
    rows: list[list[str]] = []
    cell_slots: list[list] = []
    for iface in ifaces:
        if slots is not None:
            entity = iface.get("functionId") or iface.get("globalId")
            cell_slots.append([None, None, slots.entity("description", entity,
                                                        iface.get("description")),
                               None, None, None, None, None])
        iface_type = iface.get("type", "") or "-"
        if "variableType" in iface:
            data_type = iface.get("variableType", "") or "-"
            data_range = iface.get("range", "") or "NA"
        else:
            params = iface.get("parameters", []) or []
            param_types = "; ".join(_param_type_label(p) for p in params) if params else "VOID"
            param_ranges = "; ".join(p.get("range", "") for p in params) if params else "NA"
            ret = (iface.get("returnType") or "").strip()
            if ret:
                # Only add the return line when a return type was actually captured.
                # Display void uniformly as VOID with an NA range (matches the
                # no-parameter convention: type VOID, range NA).
                is_void = ret.lower() == "void"
                ret_disp = "VOID" if is_void else ret
                ret_range = "NA" if is_void else ((iface.get("returnRange") or "").strip() or "NA")
                data_type = f"{param_types}\nreturn: {ret_disp}"
                data_range = f"{param_ranges}\nreturn: {ret_range}"
            else:
                data_type = param_types
                data_range = param_ranges
        rows.append([
            str(iface.get("interfaceId", "")),
            str(iface.get("interfaceName") or iface.get("name", "")),
            str(iface.get("description", "") or "-"),
            data_type,
            data_range,
            str(iface.get("direction") or "-"),
            str(iface.get("sourceDest") or "-"),
            iface_type,
        ])
    table = {
        "headers": ["Interface ID", "Interface Name", "Information", "Data Type",
                    "Data Range", "Direction(In/Out)", "Source/Destination", "Interface Type"],
        "rows": rows,
    }
    if slots is not None:
        table["cell_slots"] = cell_slots
    return table


# ── Introduction builder (Purpose / Scope / Terms — mirrors docx_exporter) ────

def build_intro_section(config: dict, abbreviations: dict,
                        components: list[str], project_name: str) -> dict:
    """Build the "1 Introduction" section (1.1 Purpose, 1.2 Scope, 1.3 Terms,
    Abbreviations and Definitions) exactly as ``docx_exporter.py`` does.

    ``components`` is the sorted list of component display keys; the Scope body
    lists them as bullets. Shared by the live render and the synthesized /
    compare fallbacks so the UI always matches the exported DOCX.
    """
    intro_cfg = (config.get("docx") or {}).get("introduction") or {}
    purpose_text = intro_cfg.get("purpose", "[Purpose of this document.]").replace("{project_name}", project_name)
    scope_intro = intro_cfg.get("scopeIntro", "[Scope of the software detailed design.]").replace("{project_name}", project_name)
    scope_body = intro_cfg.get("scopeBody", "")
    scope_items: list[str] = intro_cfg.get("scopeItems") or []

    # display_name(): component ids are layer-qualified (`Layer1.Core`), and this bullet
    # list has to read exactly like the DOCX Scope section, which shows the bare name.
    # Identity stays qualified everywhere it is a key — including meta.components below.
    from core.config import display_name
    sorted_comps = sorted(components)
    comp_bullets = "\n".join(f"• {display_name(c).replace('-', ' ')}" for c in sorted_comps)
    scope_text = scope_intro
    if comp_bullets:
        scope_text += "\n" + comp_bullets
    if scope_body:
        scope_text += "\n" + scope_body
    if scope_items:
        scope_text += "\n" + "\n".join(f"- {item}" for item in scope_items)

    if abbreviations:
        terms_sec = _sec("intro-terms", "1.3", "Terms, Abbreviations and Definitions", 2,
                         type="table",
                         table={"headers": ["Term", "Description"],
                                "rows": [[k, v] for k, v in sorted(abbreviations.items())]})
    else:
        terms_sec = _sec("intro-terms", "1.3", "Terms, Abbreviations and Definitions", 2,
                         type="richtext", content="[Terms, abbreviations and definitions.]")

    return _sec("intro", "1", "Introduction", 1, type="richtext", content=None, children=[
        _sec("intro-purpose", "1.1", "Purpose", 2, type="richtext", content=purpose_text),
        _sec("intro-scope", "1.2", "Scope", 2, type="richtext", content=scope_text),
        terms_sec,
    ])


def render_config(version: Any = None) -> dict:
    """The config a document is rendered with: the one its version ran with
    (`versions.resolved_config` - what the DOCX was exported with), else the engine's."""
    return getattr(version, "resolved_config", None) or _load_config()


def intro_section_from_config(components: list[str], project_name: str, version: Any = None) -> dict:
    """Build the Introduction section from the version's config + abbreviations file —
    for callers (fallback renders) that don't already have them loaded."""
    config = render_config(version)
    return build_intro_section(config, _load_abbreviations(config), components, project_name)


# ── main builder ──────────────────────────────────────────────────────────────

def build_render(doc, project, version, group_dir: Path, project_id: str,
                 *, model_root: Optional[Path] = None,
                 asset_base: Optional[str] = None,
                 model_reader: Optional[Any] = None,
                 output_reader: Optional[Any] = None,
                 overrides: Optional[dict] = None) -> dict:
    """Build a rich {cover, toc, sections, meta} payload mirroring the DOCX structure.

    Every text a reviewer can correct carries its `slot` (`_Slots`): ``cell_slots`` beside a
    table's ``rows``, ``*_slot`` in a function's or behaviour row's table, ``content_slot`` on a
    function section without a flowchart. ``overrides`` is `load_overrides`' result, read here
    when not given.

    ``model_root`` overrides where model/*.json is read from (defaults to the live
    ``model/`` dir); ``asset_base`` overrides the URL prefix used for diagram assets
    (defaults to the live document-asset route). Both let the compare engine build
    a render from a per-version snapshot instead of the live working tree.

    ``model_reader`` (PG-7a) is a ``services.model_reader.ModelReader`` that serves the model
    from Postgres for THIS version, falling back to ``model_root``/the live dir. When omitted the
    model is read from disk exactly as before.
    """
    group = doc.group
    if asset_base is None:
        asset_base = f"projects/{project_id}/documents/{doc.id}/assets"

    # Load interface data
    itf: dict = _view_json(output_reader, group_dir, "interface_tables.json") or {}
    # The unit header rows, built by the phase-3 view. This module used to rebuild them
    # from model JSON alone, which meant no declaration text (no checkout to read) and no
    # orphan-header symbols -- a second implementation of one rule, drifting from the
    # exporter's. Now both read the same file.
    unit_headers: dict = _view_json(output_reader, group_dir, "unit_headers.json") or {}
    unit_names: dict[str, str] = itf.get("unitNames", {}) or {}

    # Group unit keys by component
    comps: dict[str, list[str]] = {}
    for uk in unit_names:
        comps.setdefault(uk.split(KEY_SEP, 1)[0], []).append(uk)

    # Load model files — via the version-scoped reader (Postgres-first) when supplied,
    # else straight from disk as before.
    model_dir = model_root or (_REPO_ROOT / "model")
    _load = model_reader.load if model_reader is not None else (
        lambda name: _load_model_json(model_dir, name))
    units_data = _load("units")
    dd_data = _load("dataDictionary")
    globals_data = _load("globalVariables")
    functions_data = _load("functions")
    meta_data = _load("metadata")
    project_name = meta_data.get("projectName") or project.name

    # Load config + abbreviations: the version's own, as the DOCX was exported with
    config = render_config(version)
    abbreviations = _load_abbreviations(config)
    # Each unit's one-line summary, as the DOCX exporter wrote it (an LLM summary when AI is on).
    unit_descriptions: dict = _view_json(output_reader, group_dir, "unit_descriptions.json") or {}

    # Load flowcharts + behavior diagrams
    flowcharts_dir = group_dir / "flowcharts"
    flowchart_ids: dict = {}
    flowcharts_map = _load_flowcharts(flowcharts_dir, output_reader, group_dir, flowchart_ids)
    behavior_rows = _load_behavior_diagrams(group_dir, output_reader)
    slots = _Slots(load_overrides(version) if overrides is None else overrides)

    # Hidden functions
    hidden_fids: set = {fid for fid, f in functions_data.items() if f.get("hidden", False)}

    # Hidden functions by (component, unit) for behavior section filter
    _hidden_by_mod_unit: dict = {}
    for _fid in hidden_fids:
        _fp = _fid.split(KEY_SEP)
        if len(_fp) >= 3:
            _qn = (functions_data[_fid].get("qualifiedName") or "")
            _base = _qn.split("::")[-1] if _qn else _fp[2]
            _hidden_by_mod_unit.setdefault((_fp[0], _fp[1]), set()).add(_base)

    sorted_comps = sorted(comps.keys())

    # ── 1. Introduction (Purpose / Scope / Terms) ────────────────────────────
    sections: list[dict] = [
        build_intro_section(config, abbreviations, sorted_comps, project_name),
    ]

    # ── 2+. Per component ────────────────────────────────────────────────────
    for comp_idx, comp in enumerate(sorted_comps):
        n = comp_idx + 2
        # The bare component name, as the DOCX heads it; `comp` stays qualified wherever it is a key.
        from core.config import display_name
        comp_display = display_name(comp).replace("-", " ")
        unit_keys = sorted(comps[comp])

        # Build (unit_key, display_name, interfaces) triples
        unit_rows: list[tuple] = []
        for uk in unit_keys:
            uname = unit_names.get(uk, uk.split(KEY_SEP)[-1])
            ifaces = [
                i for i in (itf.get(uk, {}) or {}).get("entries", []) or []
                if i.get("functionId") not in hidden_fids
            ]
            unit_rows.append((uk, uname, ifaces))

        # ── N.1 Static Design ────────────────────────────────────────────────
        static_children: list[dict] = []

        # Container diagram (unnumbered — not a heading in DOCX)
        for fn in _pngs(group_dir, "component_container_diagrams",
                        lambda nm, c=comp: nm == f"{c}.png"):
            static_children.append(_diagram_sec(
                asset_base, group_dir, "component_container_diagrams", fn,
                f"{comp}-container", "", "Component Structure", 2,
                f"Component structure for {comp_display}.",
            ))

        # Header dependency diagram (unnumbered)
        for fn in _pngs(group_dir, "component_header_dependency_diagrams",
                        lambda nm, c=comp: nm == f"{c}.png"):
            static_children.append(_diagram_sec(
                asset_base, group_dir, "component_header_dependency_diagrams", fn,
                f"{comp}-dep", "", "Include Dependencies", 2,
                f"Include dependencies for {comp_display}.",
            ))

        # Component / Unit / Description / Note summary table (unnumbered)
        comp_unit_rows: list[list[str]] = []
        comp_unit_slots: list[list] = []
        for uk, uname, ifaces in unit_rows:
            fn_items: list[tuple] = []
            gv_items: list[tuple] = []
            for iface in ifaces:
                d = str(iface.get("description") or "").strip()
                if not d or d in ("-", "N/A"):
                    continue
                d_clean = " ".join(d.split())
                iname = (iface.get("interfaceName") or iface.get("name") or "").strip()
                if iface.get("type") == "Global Variable":
                    gv_items.append((iname, d_clean))
                else:
                    fn_items.append((iname, d_clean))
            seen_descs: set = set()
            all_descs: list[str] = []
            for _, d in fn_items + gv_items:
                if d not in seen_descs:
                    seen_descs.add(d)
                    all_descs.append(d)
            # The unit's STORED description, as the Word exporter prints it (REQ-PRE-01) -- the
            # text Phase 2 generated, or a reviewer's correction of it (`unitDescription`). The
            # join below is the exporter's fallback too, for a version generated before the
            # description was stored or with the LLM off. Showing only the join here put one
            # sentence on the page and another in the Word file, and hid a unit correction from
            # the page altogether.
            stored = str((units_data.get(uk) or {}).get("description") or "").strip()
            if stored and stored not in ("-", "N/A"):
                desc = stored
            else:
                # No stored text: what the exporter printed for the unit (unit_descriptions.json),
                # else its own fallback -- the join, trimmed as it trims.
                desc = (str(unit_descriptions.get(uk) or "").strip()
                        or _cell_trim("; ".join(all_descs), 120) or "N/A")
            comp_unit_rows.append([comp_display, uname, desc, "N/A"])
            comp_unit_slots.append([None, None, slots.unit(uk, stored), None])

        if comp_unit_rows:
            static_children.append(_sec(
                f"{comp}-unit-table", "", "Component/Unit Table", 2,
                type="table",
                table={"headers": ["Component", "Unit", "Description", "Note"],
                       "rows": comp_unit_rows, "cell_slots": comp_unit_slots},
            ))

        # ── Per unit subsections ─────────────────────────────────────────────
        for unit_idx, (uk, uname, ifaces) in enumerate(unit_rows, start=1):
            unit_sec_num = f"{n}.1.{unit_idx}"
            unit_prefix = uk.replace(KEY_SEP, "_").replace(" ", "_")
            unit_name_fc = uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uname
            unit_children: list[dict] = []

            # Unit diagram (unnumbered)
            for fn in _pngs(group_dir, "unit_diagrams",
                            lambda nm, p=f"{comp}_{uname}": nm == f"{p}.png"):
                unit_children.append(_diagram_sec(
                    asset_base, group_dir, "unit_diagrams", fn,
                    f"unit-{uk}", "", f"Unit — {uname}", 3,
                    f"Static structure of unit {uname}.",
                ))

            # N.1.U.1 unit header
            unit_info = units_data.get(uk) or {}
            header_rows = unit_headers.get(uk) or []
            if header_rows:
                hdr_rows: list[list[str]] = []
                hdr_slots: list[list] = []
                for r in header_rows:
                    info = r.get("information", "N/A")
                    type_key = r.get("typeKey")
                    struct_slot = None
                    if type_key:
                        # A record's description (`structDescription`): read from the model,
                        # where a save writes it. The row's copy is Phase 3's, so it showed the
                        # old text until a re-export; its name-derived stand-in stays when the
                        # model has none.
                        stored_struct = str((dd_data.get(type_key) or {}).get("description")
                                            or "").strip()
                        info = stored_struct or info
                        struct_slot = slots.entity("structDescription", type_key, stored_struct)
                    hdr_rows.append([r.get("declaration", "N/A"), info])
                    hdr_slots.append([None, struct_slot])
                hdr_table = {
                    "headers": ["global variables / typedef / enum / define", "information"],
                    "rows": hdr_rows, "cell_slots": hdr_slots,
                }
                unit_children.append(_sec(f"{uk}-header", f"{unit_sec_num}.1", "unit header", 4,
                                          type="table", table=hdr_table))
            else:
                unit_children.append(_sec(f"{uk}-header", f"{unit_sec_num}.1", "unit header", 4,
                                          type="richtext", content="NA"))

            # N.1.U.2 unit interface (8-column; header only when the unit has none, as in the DOCX)
            unit_children.append(_sec(f"{uk}-iface", f"{unit_sec_num}.2", "unit interface", 4,
                                      type="table", table=_interfaces_table_8col(ifaces, slots)))

            # N.1.U.3+ per function (functions only, starting at index 3)
            iface_idx = 3
            rendered_private_fids: set = set()
            for iface in (i for i in ifaces if i.get("type") != "Global Variable"):
                func_name = iface.get("name", "") or iface.get("interfaceName", "")
                if not func_name:
                    continue
                # Class-qualified for display; func_name stays short as a lookup key.
                func_display = iface.get("interfaceName", "") or func_name
                func_qn = iface.get("qualifiedName", "") or func_name

                # Flowchart lookup (mirrors docx_exporter). Flowcharts are keyed by
                # qualifiedName (flowchart/output/writer.py), so try that FIRST — looking up by
                # short name alone meant class methods never resolved and silently rendered
                # without a flowchart here, unlike the DOCX.
                found = _find_flowchart(flowcharts_map, (unit_prefix, unit_name_fc),
                                        (func_qn, func_name))
                flowchart_entries: list[dict] = []

                if found:
                    params = iface.get("parameters") or []
                    params_str = ", ".join(
                        f"{p.get('type', '')} {p.get('name', '')}".strip() for p in params
                    )
                    ret = iface.get("returnType", "") or ""
                    signature = f"{ret} {func_display}({params_str})".strip()
                    flowchart_entries.append(
                        _flowchart_entry(group_dir, found, signature, asset_base, flowchart_ids))

                # Private callee flowcharts (mirrors docx_exporter)
                fid = iface.get("functionId")
                if fid and functions_data:
                    callee_fids = (functions_data.get(fid) or {}).get("callsIds") or []
                    for callee_fid in callee_fids:
                        if callee_fid in hidden_fids or callee_fid in rendered_private_fids:
                            continue
                        callee = functions_data.get(callee_fid) or {}
                        if (callee.get("visibility") or "").lower() != "private":
                            continue
                        callee_qn = callee.get("qualifiedName", "")
                        callee_fn = callee_qn.split("::")[-1] if callee_qn else ""
                        if not callee_fn:
                            continue
                        callee_parts = callee_fid.split(KEY_SEP)
                        c_unit_key = KEY_SEP.join(callee_parts[:2]) if len(callee_parts) >= 2 else ""
                        c_prefix = c_unit_key.replace(KEY_SEP, "_").replace(" ", "_")
                        c_unit_name = callee_parts[1] if len(callee_parts) > 1 else ""
                        callee_found = _find_flowchart(flowcharts_map, (c_prefix, c_unit_name),
                                                       (callee_qn, callee_fn))
                        if not callee_found:
                            continue
                        rendered_private_fids.add(callee_fid)
                        callee_display = scoped_name(callee_qn, callee.get("className", ""))
                        callee_params = callee.get("params") or callee.get("parameters") or []
                        cparams_str = ", ".join(
                            f"{p.get('type', '')} {p.get('name', '')}".strip()
                            for p in callee_params
                        )
                        callee_sig = f"{callee.get('returnType', '')} {callee_display}({cparams_str})".strip()
                        flowchart_entries.append(
                            _flowchart_entry(group_dir, callee_found, callee_sig, asset_base,
                                             flowchart_ids))

                # Input / output names (mirrors docx_exporter)
                fn_data = (functions_data.get(fid) or {}) if fid else {}
                input_name = (fn_data.get("behaviourInputName") or "").strip()
                output_name = (fn_data.get("behaviourOutputName") or "").strip()
                if not input_name:
                    lbl = _readable_label(func_name)
                    input_name = (lbl + " input").strip() if lbl else ""
                if not output_name:
                    lbl = _readable_label(func_name)
                    output_name = (lbl + " result").strip() if lbl else ""

                description = iface.get("description", "") or "-"
                sec_id = f"{uk}-fn-{_safe_fn(func_qn)}"
                sec_title = f"{uname}-{func_display}"
                # The function's correctable texts: the same `description` slot as its
                # interface-table row, and its two behaviour names (read from the model, not
                # the "X input" stand-ins above).
                description_slot = slots.entity("description", fid, iface.get("description"))

                if flowchart_entries:
                    # The Requirements cell opens with the description, else the function's
                    # name (docx_exporter._add_flowchart_table).
                    requirement = (iface.get("description") or "").strip() or func_display or "-"
                    unit_children.append(_sec(
                        sec_id, f"{unit_sec_num}.{iface_idx}", sec_title, 4,
                        type="flowchart_table", content=requirement,
                        flowchart_table={
                            "description": requirement,
                            "flowcharts": flowchart_entries,
                            "risk": "Medium",
                            "capacity": "Common",
                            "input_name": input_name,
                            "output_name": output_name,
                            "description_slot": description_slot,
                            "input_name_slot": slots.entity(
                                "behaviourInputName", fid, fn_data.get("behaviourInputName")),
                            "output_name_slot": slots.entity(
                                "behaviourOutputName", fid, fn_data.get("behaviourOutputName")),
                        },
                    ))
                else:
                    fn_sec = _sec(
                        sec_id, f"{unit_sec_num}.{iface_idx}", sec_title, 4,
                        type="richtext", content=description,
                    )
                    fn_sec["content_slot"] = description_slot
                    unit_children.append(fn_sec)
                iface_idx += 1

            static_children.append(_sec(
                f"{comp}-unit-{unit_idx}", unit_sec_num, uname, 3,
                type="richtext", content=None, children=unit_children,
            ))

        # ── N.2 Dynamic Behaviour ────────────────────────────────────────────
        dyn_children: list[dict] = []
        dyn_idx = 1
        for unit_name_beh, entries in sorted((behavior_rows.get(comp) or {}).items()):
            for row in entries:
                current_fn = row.get("currentFunctionName", "") or ""
                # Hide/resolve by fid — the short-name-per-unit set hid every same-named method
                # in the unit, and the scan below returned whichever one came first.
                current_fid = row.get("currentFunctionId", "") or ""
                if current_fid:
                    if current_fid in hidden_fids:
                        continue
                elif current_fn in _hidden_by_mod_unit.get((comp, unit_name_beh), set()):
                    continue  # pre-currentFunctionId artifacts
                ext = row.get("externalUnitFunction", "") or ""
                current_display = row.get("currentFunctionDisplay", "") or current_fn
                subheader = f"{unit_name_beh} - {current_display}"
                if ext:
                    subheader += f" ({ext})"

                # Input / output names from functions model
                input_label = ""
                output_label = ""
                _beh_f = functions_data.get(current_fid) if current_fid else None
                beh_fid = current_fid if _beh_f is not None else None
                if _beh_f is None:
                    for fid, f in functions_data.items():
                        fp = fid.split(KEY_SEP)
                        if len(fp) < 3 or fp[0] != comp or fp[1] != unit_name_beh:
                            continue
                        qn = f.get("qualifiedName", "") or ""
                        if (qn.split("::")[-1] if qn else "") != current_fn:
                            continue
                        _beh_f = f
                        beh_fid = fid
                        break
                if _beh_f is not None:
                    input_label = (_beh_f.get("behaviourInputName") or "").strip()
                    output_label = (_beh_f.get("behaviourOutputName") or "").strip()
                if not input_label:
                    lbl = _readable_label(current_fn)
                    input_label = (lbl + " input").strip() if lbl else "Behaviour input"
                if not output_label:
                    lbl = _readable_label(current_fn)
                    output_label = (lbl + " result").strip() if lbl else "Behaviour result"

                # Behavior PNG URL
                png_abs = row.get("pngPath")
                diagram_url: Optional[str] = None
                if png_abs:
                    try:
                        rel = Path(str(png_abs)).relative_to(group_dir)
                        diagram_url = (
                            f"{asset_base}/{rel.as_posix()}"
                        )
                    except (ValueError, TypeError):
                        pass

                bullets = _as_description_list(row.get("behaviorDescription"))
                beh_names = _beh_f or {}
                dyn_children.append(_sec(
                    f"{comp}-dyn-{dyn_idx}", f"{n}.2.{dyn_idx}", subheader, 3,
                    type="behavior_table", content=None,
                    behavior_table={
                        "description_list": bullets,
                        "risk": "Medium",
                        "capacity": "Common",
                        "input_name": input_label,
                        "output_name": output_label,
                        "diagram_url": diagram_url,
                        # The row is addressed by both functions (`for_behaviour_row`); a row
                        # from before `externalCallerId` has no slot, as R11 skips it too.
                        "description_slot": slots.behaviour(
                            current_fid, row.get("externalCallerId"), bullets),
                        "input_name_slot": slots.entity(
                            "behaviourInputName", beh_fid, beh_names.get("behaviourInputName")),
                        "output_name_slot": slots.entity(
                            "behaviourOutputName", beh_fid, beh_names.get("behaviourOutputName")),
                    },
                ))
                dyn_idx += 1

        sections.append(_sec(
            f"comp-{comp}", str(n), comp_display, 1, type="richtext", content=None,
            children=[
                _sec(f"{comp}-static", f"{n}.1", "Static Design", 2,
                     type="richtext", content=None, children=static_children),
                _sec(f"{comp}-dynamic", f"{n}.2", "Dynamic Behaviour", 2,
                     type="richtext", content=None, children=dyn_children),
            ],
        ))

    # ── Code Metrics ─────────────────────────────────────────────────────────
    metrics_n = len(sorted_comps) + 2
    sections.append(_sec(
        "metrics", str(metrics_n),
        "Code Metrics, Coding Rule, Test Coverage", 1,
        type="richtext", content="[Code metrics, coding rules and test coverage.]",
    ))

    # ── Appendix A ────────────────────────────────────────────────────────────
    # Number + title read "Appendix A. Design Guideline", the DOCX heading.
    sections.append(_sec(
        "appendix-a", "Appendix A.",
        "Design Guideline", 1,
        type="richtext", content="[Design guidelines.]",
    ))

    # ── Meta ─────────────────────────────────────────────────────────────────
    all_entries = [
        e for uk in unit_names
        for e in (itf.get(uk, {}) or {}).get("entries", []) or []
    ]
    functions_total = sum(1 for e in all_entries if e.get("type") == "Function")
    globals_total = sum(1 for e in all_entries
                        if e.get("type") in ("Variable", "Global", "GlobalVariable"))

    cover = {
        "project_name": project_name,
        "subtitle": doc.subtitle or "Software Detailed Design Specification",
        "version": version.tag if version else doc.version_id,
        "layer": doc.layer,
        "group": group,
        "standard": project.compliance_standard,
        "process": doc.process,
        "generated_at": doc.updated_at.isoformat(),
    }
    meta = {
        "pipeline_data_available": True,
        "model_data_available": True,
        "source": "pipeline",
        "layers": [doc.layer] if doc.layer else [],
        "components": sorted_comps,
        "units_total": len(unit_names),
        "functions_total": functions_total,
        "globals_total": globals_total,
    }
    return {"cover": cover, "toc": _flatten_toc(sections), "sections": sections, "meta": meta}
