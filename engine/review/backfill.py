"""Unit and struct descriptions for a version generated before Phase 2 stored them (BACKLOG RF-6).

Phase 2 generates a unit's description and a struct/class/union's description and stores them in
the model (REQ-PRE-01, PR #70); the exporter, the unit-header view and the web page only read them,
falling back to deterministic text -- the join of the unit's interface descriptions, a sentence
made from a record's name. A version generated before that stores none. Its LLM wording survives
only in its own earlier output: `unit_descriptions.json` (the Component/Unit table, as the exporter
wrote it) and `unit_headers.json` (each record row's Information). A re-export then printed the
fallback instead, and the document lost text it had.

`backfill` copies that wording into the model, where it would have been:

- only for a version generated with LLM descriptions on (`versions.resolved_config`), since
  without the LLM the earlier output holds the fallback text itself;
- only for a version that stores no description of that kind at all -- one made before the move;
- only into an empty field, and never a fallback text or one two units disagree about.

The version then reads like one generated today: the Word file keeps its wording on re-export, a
reviewer's correction records it as the LLM original, and an undo puts it back. Reading the old
output at export time instead would have broken that undo -- after a correction and a re-export,
the old output holds the correction. Run by `analyzer.py setup` (`tools/db_setup.py`); a second run
finds nothing to do.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, Iterator, List, Set

from sqlalchemy import select

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

#: What the old output printed when it had no text to print.
_NO_TEXT = ("", "-", "N/A")

_RECORD_DECL_RE = re.compile(r"^\s*(?:typedef\s+)?(?:struct|class|union)\b\s*([A-Za-z_]\w*)?")
_TYPEDEF_ALIAS_RE = re.compile(r"\}\s*([A-Za-z_]\w*)\s*;\s*$")


def backfill(conn, version_id: str) -> Dict[str, int]:
    """Store the version's earlier LLM wording as its descriptions. `{"units": n, "structs": m}`."""
    done = {"units": 0, "structs": 0}
    if not _llm_described(conn, version_id):
        return done
    done["units"] = _backfill_units(conn, version_id)
    done["structs"] = _backfill_structs(conn, version_id)
    return done


def _llm_described(conn, version_id: str) -> bool:
    row = conn.execute(select(s.versions.c.resolved_config)
                       .where(s.versions.c.id == version_id)).first()
    cfg = row.resolved_config if row is not None else None
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except ValueError:
            return False
    return bool(((cfg or {}).get("llm") or {}).get("descriptions"))


def _stored(conn, version_id: str, file_name: str) -> Iterator[object]:
    """Every `<group>/<file_name>` the version stored, parsed."""
    vf = s.version_output_files
    for r in conn.execute(select(vf.c.content).where(vf.c.version_id == version_id,
                                                     vf.c.rel_path.like("%/" + file_name))):
        try:
            yield json.loads(r.content or "null")
        except ValueError:
            continue


def _backfill_units(conn, version_id: str) -> int:
    from core import model_store
    units = model_store.load_units(conn, version_id)
    if any(str(u.get("description") or "").strip() for u in units.values()):
        return 0                     # Phase 2 stored them: made since the move
    done = 0
    for table in _stored(conn, version_id, "unit_descriptions.json"):
        if not isinstance(table, dict):
            continue
        for unit_key, text in table.items():
            text = str(text or "").strip()
            unit = units.get(unit_key)
            if text in _NO_TEXT or unit is None or str(unit.get("description") or "").strip():
                continue
            model_store.set_unit_description(conn, version_id, unit_key, text)
            unit["description"] = text
            done += 1
    return done


def record_names(declaration: str) -> List[str]:
    """The names a unit-header record row declares: `class X`, `struct X {...}`, and a typedef's
    alias (`typedef struct [Tag] { ... } Alias;`). [] for any other row."""
    m = _RECORD_DECL_RE.match(declaration or "")
    if not m:
        return []
    names = [m.group(1)] if m.group(1) else []
    if declaration.lstrip().startswith("typedef"):
        alias = _TYPEDEF_ALIAS_RE.search(declaration.strip())
        if alias and alias.group(1) not in names:
            names.append(alias.group(1))
    return names


def _backfill_structs(conn, version_id: str) -> int:
    from core import model_store
    from utils import RECORD_KINDS
    from views.unit_headers import _RECORD_LABEL, _struct_info_from_name
    records = {k: e for k, e in model_store.load_types(conn, version_id).items()
               if (e or {}).get("kind") in RECORD_KINDS}
    if any(str(e.get("description") or "").strip() for e in records.values()):
        return 0                     # Phase 2 stored them: made since the move
    wording: Dict[str, Set[str]] = {}
    for table in _stored(conn, version_id, "unit_headers.json"):
        if not isinstance(table, dict):
            continue
        for rows in table.values():
            for row in rows or []:
                info = str((row or {}).get("information") or "").strip()
                if info in _NO_TEXT:
                    continue
                for name in record_names(str(row.get("declaration") or "")):
                    wording.setdefault(name, set()).add(info)
    done = 0
    for key, entry in records.items():
        name = entry.get("name") or key
        fallbacks = {_struct_info_from_name(n, label)
                     for n in {name, key} for label in _RECORD_LABEL.values()}
        texts = (wording.get(name, set()) | wording.get(key, set())) - fallbacks
        if len(texts) != 1:
            continue                 # none, or two rows disagree: nothing safe to copy
        model_store.set_entity_field(conn, version_id, key, "description", texts.pop(),
                                     ("type", "macro"))
        done += 1
    return done
