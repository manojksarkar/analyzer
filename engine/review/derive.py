"""Which views an override invalidates, and re-deriving them.

`REQ-AP-01`: the model is the single source of truth and every view output is derived from it.
So an override is not finished when the model is written — the rows the document actually reads
are still the ones Phase 3 wrote last time.

This is not hypothetical. `interface_tables.json` holds a **copy** of `description`
(`views/interface_tables.py`), and the DOCX exporter reads the copy. Updating only the model
changes nothing in the document.

## The mapping

| slot kind | view |
|---|---|
| `description` | `interfaceTables` **and** `testSpecs` (a SWE.4 spec copies it) |
| `behaviourInputName`, `behaviourOutputName`, `unitDescription` | `interfaceTables` |
| `structDescription` | `unitHeaders` (the unit header table's information column) |
| `behaviourDescription` | `behaviourDiagram` |
| `nodeLabel` | `flowcharts` **and** `testSpecs` (`REQ-CS-04`) |

Scoped to one component through `config["_analyzerAllowedComponents"]`, which every view already
honours. A view is `run(model, output_dir, model_dir, config)` and is a pure function of the
model plus config — no LLM, no parse, no subprocess — so re-deriving one component is cheap.

`nodeLabel` carries two views because a Dynamic Behaviour spec does not merely name a cross-unit
callee — it transcribes that callee's flowchart steps in place, and chains onward. A label
corrected in one unit therefore changes **another** unit's document (`REQ-CS-04`).

## Nothing else may write a view's output

`REQ-AP-01` holds because the rows are derived. There are exactly two writers —
`model_store.persist_output_files` and `review.rerender.write_output_row` — and
`tests/unit/test_output_row_writers.py` fails if a third appears. If one does, the rows can say
something their source does not and the two-copies bug class is back.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from review import resolver, slot

#: slot kind -> the views that must be re-derived. Tuples so a kind can grow a second view
#: without every caller changing shape.
VIEWS_BY_KIND: Dict[str, Tuple[str, ...]] = {
    # testSpecs too: a SWE.4 spec carries a copy of its function's description
    # (views/test_specs.py), and the SWE.4 exporter prints that copy.
    slot.DESCRIPTION:           ("interfaceTables", "testSpecs"),
    slot.BEHAVIOUR_INPUT_NAME:  ("interfaceTables",),
    slot.BEHAVIOUR_OUTPUT_NAME: ("interfaceTables",),
    slot.UNIT_DESCRIPTION:      ("interfaceTables",),
    # The unit header table is a Phase-3 view of its own (views/unit_headers.py), and its
    # information column for a struct, class or union row is this stored description.
    slot.STRUCT_DESCRIPTION:    ("unitHeaders",),
    slot.BEHAVIOUR_DESCRIPTION: ("behaviourDiagram",),
    # flowcharts AND testSpecs (REQ-CS-04). A Dynamic Behaviour spec transcribes a
    # cross-unit callee's steps in place -- and chains onward -- so a label corrected in one
    # unit changes ANOTHER unit's document. Re-deriving the component's specs rather than
    # computing who transcribes whom: that view calls no LLM, so it is cheap, and correct by
    # construction instead of correct-if-the-traversal-is-right.
    slot.NODE_LABEL:            ("flowcharts", "testSpecs"),
}


def views_for(slot_kind: str) -> Tuple[str, ...]:
    """The views `slot_kind` invalidates. Raises for a kind that is not editable.

    Not `.get(kind, ())`: a kind nobody mapped would then quietly invalidate nothing, the model
    would hold the human's text, the document would keep the LLM's, and the only symptom would
    be an edit that appears to save and never shows up.
    """
    try:
        return VIEWS_BY_KIND[slot_kind]
    except KeyError:
        raise slot.SlotKeyError(
            "no view mapping for slot kind %r; every editable kind needs one or its override "
            "never reaches the document" % slot_kind) from None


def component_of(slot_kind: str, slot_key: str) -> str:
    """The component whose views an override touches.

    Every addressed id — `entity_key` and `unit_key` alike — starts with the component, which is
    how `model_store._split_key` reads it too. Taking the first segment is safe in a way that
    splitting a *composite* slot key on `|` is not: this is the id's own first field, not a
    boundary between two ids.
    """
    parts = slot.parse(slot_kind, slot_key)
    ident = parts.get("entity_key") or parts.get("unit_key") or parts.get("function_id") or ""
    return ident.split("|")[0]


def make_deriver(output_dir: str,
                 model_dir: str,
                 config: Dict[str, Any],
                 model: Optional[Dict[str, Any]] = None,
                 model_loader: Optional[Callable[[], Dict[str, Any]]] = None) -> Callable[..., Sequence[str]]:
    """A `derive=` callable for `override_service.apply_override`.

    The model is re-read (or re-supplied) at call time rather than captured here, because the
    override has just changed it — deriving from a snapshot taken before the write would
    regenerate the view from the text the reviewer replaced, which looks exactly like the edit
    not saving.
    """
    def _derive(*, version_id: str, slot_kind: str, **_kw) -> Sequence[str]:
        from views.registry import VIEW_REGISTRY

        names = views_for(slot_kind)
        current = model if model is not None else (model_loader() if model_loader else None)
        if current is None:
            raise ValueError("make_deriver needs `model` or `model_loader`: a view is a pure "
                             "function of the model and cannot be run without one")

        scoped = dict(config or {})
        done = []
        for name in names:
            view = VIEW_REGISTRY.get(name)
            if view is None:
                # A registry that has lost a view is not something to work around: the document
                # would silently keep the old text.
                raise KeyError("view %r is not registered; %s overrides cannot be applied"
                               % (name, slot_kind))
            view(current, output_dir, model_dir, scoped)
            done.append(name)
        return done

    return _derive


def scoped_config(config: Dict[str, Any], component: str) -> Dict[str, Any]:
    """`config` narrowed to one component, for the views that honour the key.

    Returned as a copy: the run's config is shared, and narrowing it in place would leave every
    later view in the process scoped to whichever component was edited last.
    """
    out = dict(config or {})
    if component:
        out["_analyzerAllowedComponents"] = [component]
    return out
