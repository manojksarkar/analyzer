"""Rewriting the texts written from a corrected text -- inside a Word-file update.

FAST_WORD_FILE_UPDATES P5, decided with the user (D1, D3). A correction leaves the LLM texts written
FROM the corrected text describing wording the reviewer rejected. The save records them in the
regeneration queue (`cascade.dependents_of`: the candidates); the Word-file update of their
component rewrites them before it exports:

    in the update's components   one in another component waits for that component's update (D3)
    not a reviewer's own text    REQ-CS-03, checked again as each one is stored
    not in an approved document  it waits until the document is reopened, as a correction does
    its prompt moved             built twice without the LLM -- from the model as the LLM saw it
                                 (every description correction in force taken back to its LLM
                                 original) and from the model as it is -- and compared: a prompt
                                 cut to its token budget may not carry the corrected text at all
    rewritten                    by the generator that wrote it, from the model as it is now,
                                 stored where Phase 2 or 3 stores it, through the save's writers

One level (REQ-CS-02): a text is rewritten because its prompt holds a corrected text, never because
it holds one this step has just rewritten.

    description (function)   llm_enrichment.enrich_functions_rich(regenerate=, only=)
    description (global)     llm_enrichment.enrich_globals_rich
    unitDescription          llm_enrichment.get_unit_description
    inputName (both names)   model_deriver's input and output names, static then the LLM
    behaviourDescription     CallDescriptionGenerator, call by call
    flowchartLabels          handed to Phase 3: the flowchart engine writes those charts' labels
                             again, past its cache (`write_labels_request`, run.py --rewrite-labels)

A text whose rewrite fails -- the LLM unreachable, no answer -- keeps its words and its queue entry,
and the next update tries again. A version made without the LLM rewrites nothing.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import sys
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from sqlalchemy import select

if __name__ == "__main__":       # a process of its own (`main`): the engine's packages, as a phase
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from review import slot          # noqa: E402
from review.cascade import FLOWCHART_LABELS   # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

#: The kinds this step rewrites, in the order it rewrites them: descriptions first, as Phase 2
#: does, so a unit description is written from its functions' new ones.
KINDS = (slot.DESCRIPTION, slot.UNIT_DESCRIPTION, slot.INPUT_NAME, slot.BEHAVIOUR_DESCRIPTION,
         FLOWCHART_LABELS)


class Result(NamedTuple):
    rewritten: Dict[str, int]       #: kind -> texts rewritten and stored
    unchanged: int                  #: candidates whose prompt did not move: retired
    waiting: int                    #: kept queued -- an approved document, no LLM, a failure
    charts: List[str]               #: flowcharts whose labels Phase 3 writes again
    failed: List[str]               #: "kind key: why"

    @property
    def total(self) -> int:
        return sum(self.rewritten.values())


NOTHING = Result({}, 0, 0, [], [])


# ---------------------------------------------------------------------------
# the step
# ---------------------------------------------------------------------------
def queued(engine, version_id: str, components: Optional[Iterable[str]] = None
           ) -> List[Tuple[str, str]]:
    """`(kind, key)` of the queued texts this step rewrites, of `components` (every component when
    None), oldest first."""
    from review import cascade
    from review.export_guard import component_id

    want = None if components is None else {component_id(c) for c in components}
    with engine.connect() as cx:
        return [(e.slot_kind, e.slot_key) for e in cascade.pending(cx, version_id)
                if e.slot_kind in KINDS
                and (want is None or _component(e.slot_kind, e.slot_key) in want)]


def rewrite_queued(engine, version_id: str, components: Optional[Iterable[str]] = None, *,
                   config: Dict[str, Any], base_path: str,
                   log: Callable[[str], None] = print) -> Result:
    """Rewrite the queued texts of `components` (every component when None) of `version_id`.

    `config` is the version's run config, `base_path` its source checkout -- a description's prompt
    holds its function's source. The run context's project scopes the LLM caches, as in a phase.
    Chart labels are not written here: `Result.charts` names them for Phase 3, and their entries
    are retired once the run that rewrote them is stored (`labels_done`)."""
    from review import cascade

    entries = queued(engine, version_id, components)
    if not entries:
        return NOTHING
    if not (config.get("llm") or {}).get("descriptions", True):
        log("%d text(s) written from corrected ones stay queued: this version is made without "
            "the LLM" % len(entries))
        return Result({}, 0, len(entries), [], [])

    world = _World.load(engine, version_id, config, base_path)
    with engine.connect() as cx:
        human = _overridden(cx, version_id)
        approved = _approved_components(cx, version_id)
    plan: Dict[str, List[str]] = {k: [] for k in KINDS}
    retire: List[Tuple[str, str]] = []
    waiting = 0
    charts = None
    for kind, key in entries:
        if _is_human(human, kind, key):
            retire.append((kind, key))          # the reviewer's own text stays (REQ-CS-03)
            continue
        if kind == FLOWCHART_LABELS:
            if charts is None:
                with engine.connect() as cx:
                    charts = _stored_charts(cx, version_id)
            qn = (world.now.functions.get(key) or {}).get("qualifiedName")
            if key not in charts[0] and qn not in charts[1]:
                retire.append((kind, key))      # printed nowhere: no labels to write again
                continue
        if _component(kind, key) in approved:
            waiting += 1                        # until the document is reopened
            continue
        try:
            moved = world.moved(kind, key)
        except Exception as exc:                # noqa: BLE001 -- cannot tell: rewrite it
            log("could not compare the prompt of %s %s (%s); rewriting it" % (kind, key, exc))
            moved = True
        if moved is False:
            retire.append((kind, key))
        else:
            plan[kind].append(key)

    if retire:
        with engine.begin() as cx:
            for kind, key in retire:
                cascade.clear(cx, version_id, kind, key)

    done: Dict[str, int] = {}
    failed: List[str] = []
    writer = _Writer(engine, version_id, world)
    for kind, run in ((slot.DESCRIPTION, _rewrite_descriptions),
                      (slot.UNIT_DESCRIPTION, _rewrite_units),
                      (slot.INPUT_NAME, _rewrite_names),
                      (slot.BEHAVIOUR_DESCRIPTION, _rewrite_rows)):
        if not plan[kind]:
            continue
        try:
            n, why = run(world, writer, plan[kind])
        except Exception as exc:                # noqa: BLE001 -- the texts keep their words
            n, why = 0, ["%s: %s" % (kind, exc)]
        done[kind] = n
        failed += why
    writer.finish()
    _flush_caches(config)

    result = Result({k: v for k, v in done.items() if v}, len(retire), waiting + len(failed),
                    sorted(plan[FLOWCHART_LABELS]), failed)
    log("texts written from corrected ones: %d rewritten (%s), %d did not need it, %d chart(s) "
        "for Phase 3, %d waiting" % (
            result.total, ", ".join("%s %d" % kv for kv in sorted(result.rewritten.items()))
            or "none", result.unchanged, len(result.charts), result.waiting))
    for line in failed[:20]:
        log("  not rewritten, stays queued: %s" % line)
    return result


def scope_components(config: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """The components an update of `scope` writes -- None for the whole version. One update
    rewrites only these components' texts (D3)."""
    scope = scope or {}
    stype, names = scope.get("type") or "project", list(scope.get("names") or [])
    if stype == "component":
        return names or None
    from core.config import get_flat_groups, get_layer_flat_groups, resolve_group_id
    if stype == "group":
        groups = get_flat_groups(config) or {}
        out: List[str] = []
        for name in names:
            gid = name if name in groups else resolve_group_id(groups, name)[0]
            grp = groups.get(gid) if gid else None
            out += list(grp.keys()) if isinstance(grp, dict) else []
        return out
    if stype == "layer":
        out = []
        for name in names:
            for grp in (get_layer_flat_groups(config, name) or {}).values():
                out += list(grp.keys()) if isinstance(grp, dict) else []
        return out
    return None


# ---------------------------------------------------------------------------
# the chart labels: Phase 3's part
# ---------------------------------------------------------------------------
def write_labels_request(path: str, charts: Iterable[str]) -> Optional[str]:
    """Write the flowcharts whose labels Phase 3 writes again -- run.py `--rewrite-labels <path>`
    -- and return `path`; None, with nothing left at `path`, when there are none. The flowcharts
    view appends each chart it wrote again to `report_path(path)`."""
    keys = sorted(set(charts or ()))
    for stale in (path, report_path(path)):
        if os.path.isfile(stale):
            os.remove(stale)
    if not keys:
        return None
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"keys": keys, "report": report_path(path)}, fh, indent=2)
    return path


def report_path(request_path: str) -> str:
    return request_path + ".done"


def read_labels_request(path: str) -> Dict[str, Any]:
    """`{"keys": [...], "report": path}` from a request file; empty when it is unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def labels_done(engine, version_id: str, request_path: Optional[str]) -> int:
    """Retire the chart entries the run reported rewritten. Called once the run's output is
    STORED: retired earlier, a run whose capture then failed would leave the queue saying the
    stored charts were rewritten. Returns how many."""
    if not request_path:
        return 0
    from review import cascade
    try:
        with open(report_path(request_path), encoding="utf-8") as fh:
            keys = {line.strip() for line in fh if line.strip()}
    except OSError:
        return 0
    n = 0
    with engine.begin() as cx:
        for key in sorted(keys):
            n += bool(cascade.clear(cx, version_id, FLOWCHART_LABELS, key))
    return n


# ---------------------------------------------------------------------------
# the model, as the LLM saw it and as it is
# ---------------------------------------------------------------------------
class _Side(NamedTuple):
    functions: Dict[str, dict]
    globals: Dict[str, dict]
    knowledge: Any


class _World:
    """The version's model twice, both fixed -- `then`, every description correction in force
    taken back to its LLM original, and `now` -- for the comparisons; and `live`, the model as
    this step leaves it, which the rewrites read and update."""

    def __init__(self, version_id, config, base_path, now: _Side, then: _Side, units,
                 components):
        self.version_id, self.config, self.base_path = version_id, config, base_path
        self.now, self.then = now, then
        self.units, self.components = units, components
        # Shallow: a rewrite replaces an entry, never edits one, so `now` stays as it was.
        self.live_functions = dict(now.functions)
        self.live_globals = dict(now.globals)
        self._tools = None
        self._pkbs: Dict[int, Any] = {}

    @classmethod
    def load(cls, engine, version_id: str, config, base_path: str) -> "_World":
        from core import model_store as ms
        with engine.connect() as cx:
            functions = ms.load_functions(cx, version_id) or {}
            globals_ = ms.load_globals(cx, version_id) or {}
            units = ms.load_units(cx, version_id) or {}
            components = ms.load_components(cx, version_id) or {}
            kb_payload = ms.load_knowledge_base(cx, version_id)
            originals = dict(cx.execute(
                select(s.text_overrides.c.slot_key, s.text_overrides.c.llm_text)
                .where(s.text_overrides.c.version_id == version_id,
                       s.text_overrides.c.slot_kind == slot.DESCRIPTION,
                       s.text_overrides.c.is_orphaned.is_(False))).fetchall())
        then_f, then_g = dict(functions), dict(globals_)
        for key, llm_text in originals.items():
            for side in (then_f, then_g):
                if key in side:
                    side[key] = {**side[key], "description": llm_text or ""}
        _ensure_paths()
        from flowchart.pkb.knowledge import load_knowledge_data, overlay_descriptions
        now_kb, then_kb = load_knowledge_data(kb_payload), load_knowledge_data(kb_payload)
        overlay_descriptions(now_kb, functions, globals_)
        overlay_descriptions(then_kb, then_f, then_g)
        return cls(version_id, config, base_path, _Side(functions, globals_, now_kb),
                   _Side(then_f, then_g, then_kb), units, components)

    # -- the comparison --------------------------------------------------------------------
    def moved(self, kind: str, key: str) -> Optional[bool]:
        """Whether `kind key`'s prompt differs between `then` and `now`. None: decided while it is
        rewritten (a behaviour row, call by call)."""
        if kind == slot.DESCRIPTION:
            if key in self.now.functions:
                return (self._function_context(key, self.now)
                        != self._function_context(key, self.then))
            qn = (self.now.globals.get(key) or {}).get("qualifiedName", "")
            return _global_sites(qn, self.now.knowledge) != _global_sites(qn, self.then.knowledge)
        if kind == slot.UNIT_DESCRIPTION:
            md = _model_deriver()
            unit_key = slot.parse(kind, key)["unit_key"]
            return (md._iface_items_for_unit(unit_key, self.units, self.now.functions,
                                             self.now.globals)
                    != md._iface_items_for_unit(unit_key, self.units, self.then.functions,
                                                self.then.globals))
        if kind == slot.INPUT_NAME:
            f = self.now.functions.get(key)
            if not f or not _names_ask_the_llm(f, self.now.globals):
                return False                    # static names: no description is in them
            return _names_globals(f, self.now.globals) != _names_globals(f, self.then.globals)
        if kind == FLOWCHART_LABELS:
            return self._label_context(key, self.now) != self._label_context(key, self.then)
        return None

    def _function_context(self, key: str, side: _Side) -> list:
        """The sections of `key`'s rich description prompt that hold OTHER texts -- callees,
        callers, repo map, globals, file siblings (`llm_enrichment._build_function_context`) --
        under each pass's budget. Its source and few-shot examples are the same on both sides."""
        from llm_core.budget import ContextBudget
        from llm_enrichment import _build_function_context
        builder, counter, max_tokens, repo_maps, tasks = self.tools()
        calls_map = {k: set(f.get("callsIds") or []) for k, f in side.functions.items()}
        return [_build_function_context(
                    key, side.functions, calls_map, {}, side.knowledge, builder,
                    repo_maps.get(id(side)), counter,
                    ContextBudget(max_tokens=max_tokens, task=task, counter=counter))
                for task in tasks]

    def tools(self):
        if self._tools is None:
            from llm_core.budget import resolve_max_tokens
            from llm_core.context_builder import ContextBuilder
            from llm_core.repo_map import RepoMap
            from llm_core.token_counter import get_counter
            from llm_enrichment import load_llm_config
            llm_cfg = load_llm_config(self.config)
            counter = get_counter(llm_cfg.get("defaultModel", ""))
            repo_maps = {id(side): RepoMap(side.knowledge)
                         for side in (self.now, self.then) if side.knowledge is not None}
            enrichment = (self.config.get("llm") or {}).get("enrichment") or {}
            tasks = (("function_description", "function_description_refined")
                     if enrichment.get("twoPassDescriptions", True) else ("function_description",))
            self._tools = (ContextBuilder(counter), counter, resolve_max_tokens(llm_cfg),
                           repo_maps, tasks)
        return self._tools

    def _label_context(self, key: str, side: _Side):
        """What a chart's label prompts take from other texts (`flowchart/llm/generator`): the
        context packet -- purpose, callers, the callee hierarchy, globals -- the called functions
        each batch names, and the function's and its callees' own descriptions. Its CFG comes from
        the source, the same on both sides."""
        pkb = self._pkbs.get(id(side))
        if pkb is None:
            _ensure_paths()
            from flowchart.pkb.builder import ProjectKnowledgeBase
            pkb = ProjectKnowledgeBase()
            pkb.build(side.functions)
            if side.knowledge is not None:
                pkb.load_project_knowledge(side.knowledge)
            self._pkbs[id(side)] = pkb
        entry = pkb.get(key)
        if entry is None:
            return None
        from flowchart.pkb.builder import _callsid_to_qname
        names: Set[str] = set()
        for cid in entry.calls_ids or ():
            qn = _callsid_to_qname(cid)
            if qn:
                names |= {qn, qn.split("::")[-1]}
        callees = tuple(sorted((c, (side.functions.get(c) or {}).get("description") or "")
                               for c in entry.calls_ids or ()))
        return (pkb.build_context_packet(entry, self.base_path),
                pkb.build_targeted_callee_context(entry, names), entry.description, callees)


def _global_sites(qn: str, knowledge) -> Tuple:
    """A global's rich prompt's writers and readers, as `enrich_globals_rich` lists them."""
    if knowledge is None or qn not in (knowledge.globals or {}):
        return ()
    gk = knowledge.globals[qn]

    def sites(names):
        out = []
        for name in (names or [])[:5]:
            fk = knowledge.functions.get(name)
            if fk:
                out.append((name, fk.description or ""))
        return tuple(out)
    return sites(gk.written_by), sites(gk.read_by)


def _names_globals(f: dict, globals_: Dict[str, dict]) -> Tuple:
    """The descriptions of the globals an input/output name prompt lists: read, then written."""
    def descs(ids):
        return tuple((gid, (globals_.get(gid) or {}).get("description") or "") for gid in ids or ())
    return (descs(f.get("readsGlobalIdsTransitive") or f.get("readsGlobalIds")),
            descs(f.get("writesGlobalIdsTransitive") or f.get("writesGlobalIds")))


def _names_ask_the_llm(f: dict, globals_: Dict[str, dict]) -> bool:
    """Whether Phase 2 asks the LLM for this function's names: only when the static ones are
    poor (`model_deriver._static_behaviour_name_is_poor`)."""
    md = _model_deriver()
    probe = copy.deepcopy(f)
    md._enrich_behaviour_names({"probe": probe}, globals_)
    return md._static_behaviour_name_is_poor(probe)


# ---------------------------------------------------------------------------
# the rewrites
# ---------------------------------------------------------------------------
def _rewrite_descriptions(world: _World, writer: "_Writer", keys: List[str]):
    from llm_enrichment import (_make_canonical_key, enrich_functions_rich,
                                enrich_globals_rich, llm_provider_reachable)
    if not llm_provider_reachable(world.config):
        return 0, ["description %s: the LLM is not reachable" % k for k in keys]
    fkeys = [k for k in keys if k in world.now.functions]
    gkeys = [k for k in keys if k not in world.now.functions and k in world.now.globals]
    failed = ["description %s: not in the model" % k for k in keys
              if k not in world.now.functions and k not in world.now.globals]
    n = 0
    if fkeys:
        # Blank, as Phase 2 asks for a rewrite (`cascade.blank_queued_text`); `regenerate` keeps
        # the cache from answering with the stale text, and `only` keeps it to these functions.
        funcs = dict(world.live_functions)
        for k in fkeys:
            funcs[k] = {**funcs[k], "description": ""}
        out = enrich_functions_rich(funcs, world.base_path, world.config,
                                    knowledge=world.now.knowledge, regenerate=set(fkeys),
                                    only=set(fkeys))
        for k in fkeys:
            text = ((out.get(k) or {}).get("description") or "").strip()
            if not text:
                failed.append("description %s: no answer from the LLM" % k)
            elif writer.description(k, text, "function"):
                n += 1
    for k in gkeys:
        g = world.live_globals[k]
        out = enrich_globals_rich({k: g}, world.live_functions, world.base_path, world.config,
                                  knowledge=world.now.knowledge)
        text = ((out.get(_make_canonical_key(g)) or {}).get("description") or "").strip()
        if not text:
            failed.append("description %s: no answer from the LLM" % k)
        elif writer.description(k, text, "global"):
            n += 1
    return n, failed


def _rewrite_units(world: _World, writer: "_Writer", keys: List[str]):
    from docx_common import load_abbreviations
    from llm_enrichment import get_unit_description, llm_provider_reachable
    if not llm_provider_reachable(world.config):
        return 0, ["unitDescription %s: the LLM is not reachable" % k for k in keys]
    md = _model_deriver()
    abbreviations = load_abbreviations(md.PROJECT_ROOT, world.config) or {}
    n, failed = 0, []
    for key in keys:
        unit_key = slot.parse(slot.UNIT_DESCRIPTION, key)["unit_key"]
        unit = world.units.get(unit_key) or {}
        fn_items, gv_items = md._iface_items_for_unit(unit_key, world.units, world.live_functions,
                                                      world.live_globals)
        display = unit.get("name") or unit_key.split("|")[-1]
        text = (get_unit_description(display, fn_items, gv_items, world.config,
                                     abbreviations) or "").strip()
        if not text or text in ("-", "N/A"):
            failed.append("unitDescription %s: no answer from the LLM" % key)
        elif writer.unit(key, unit_key, text):
            n += 1
    return n, failed


def _rewrite_names(world: _World, writer: "_Writer", keys: List[str]):
    """Both names of each function, as Phase 2 makes them: static, then the LLM for poor ones,
    then a TRUE/FALSE output name kept as one. Stored only when the LLM answered -- its silence
    leaves the static names, which must not replace its earlier ones."""
    md = _model_deriver()
    n, failed = 0, []
    for fid in keys:
        f = copy.deepcopy(world.live_functions.get(fid) or {})
        if not f:
            failed.append("inputName %s: not in the model" % fid)
            continue
        md._enrich_behaviour_names({fid: f}, world.live_globals)
        answered = md._enrich_behaviour_names_llm(world.base_path, {fid: f}, world.live_globals,
                                                  world.config) or set()
        if fid not in answered:
            failed.append("inputName %s: no answer from the LLM" % fid)
            continue
        if (f.get("outputName") or "").strip().lower() in ("true", "false"):
            f["outputName"] = "TRUE/FALSE"
        if writer.names(fid, f.get("inputName") or "", f.get("outputName") or ""):
            n += 1
    return n, failed


def _rewrite_rows(world: _World, writer: "_Writer", keys: List[str]):
    """Each queued row, call by call: a call whose prompt did not move keeps its stored words --
    and the call-description cache learns them -- and a call whose prompt moved is asked again."""
    from behaviour_diagram import SequenceDiagramGenerator
    from behaviour_diagram.selector import create_diagram_selector
    from review import phase3_overrides as p3, rerender
    gen = SequenceDiagramGenerator(world.components, world.units, world.live_functions,
                                   world.config)
    real = gen._call_description
    if not real._is_llm_available():
        return 0, ["behaviourDescription %s: the LLM is not reachable" % k for k in keys]
    selector = create_diagram_selector(gen.filter_mode, gen.function_to_unit,
                                       gen.unit_to_component, gen.functions, gen.UNKNOWN_COMPONENT)
    skip_within_unit = gen.filter_mode == "skip_within_unit"
    n, failed = 0, []
    for key in keys:
        parts = slot.parse(slot.BEHAVIOUR_DESCRIPTION, key)
        fid, caller = parts["function_id"], parts["external_caller_id"]
        with writer.engine.connect() as cx:
            found = rerender.find_behaviour_row(cx, world.version_id, fid, caller)
        if not found:
            writer.retire(slot.BEHAVIOUR_DESCRIPTION, key)      # no such row any more
            continue
        drawn_for = _drawn_for(gen, selector, fid, caller)
        if drawn_for is None:
            failed.append("behaviourDescription %s: the row's caller is not found" % key)
            continue
        bullets = _row_bullets(gen, real, world, fid, drawn_for,
                               list(found[2].get("behaviorDescription") or []), skip_within_unit)
        if bullets is None:
            writer.retire(slot.BEHAVIOUR_DESCRIPTION, key)      # no call's prompt moved
        elif any(b is None for b in bullets):
            failed.append("behaviourDescription %s: no answer from the LLM" % key)
        elif writer.row(key, parts, p3.join_bullets(bullets)):
            n += 1
    return n, failed


def _drawn_for(gen, selector, fid: str, caller: str) -> Optional[str]:
    """The caller row (`fid`, `caller`) was drawn for. The view pairs the selector's i-th caller
    with the i-th direct caller from another component (`views/behaviour_diagram.run`), and the
    selector also takes callers of callers -- so the two need not be the same function."""
    selected = selector.select_diagrams_to_generate(fid)
    component = (gen.function_to_unit.get(fid) or "").split("|", 1)[0]
    external = [c for c in ((gen.functions.get(fid) or {}).get("calledByIds") or [])
                if c and "|" in c and c.split("|")[0] != component]
    if caller not in external:
        return None
    idx = external.index(caller)
    return selected[idx][0] if idx < len(selected) else None


def _row_bullets(gen, real, world: _World, fid: str, drawn_for: str, stored: List[str],
                 skip_within_unit: bool) -> Optional[List[Optional[str]]]:
    """The row's bullets as the view makes them (`generate_diagram_for_caller`), each LLM call's
    prompt compared first: None when no call's prompt moved, else the bullets -- None in place of
    a call the LLM did not answer."""
    from llm_enrichment import _cached_desc
    calls: List[Tuple[str, str]] = []

    def placeholder(a: str, b: str) -> str:
        calls.append((a, b))
        return "\x00%d" % (len(calls) - 1)

    gen.get_call_description = placeholder              # the instance's, for this one build
    try:
        _diagram, bullets, _internal = gen.generate_diagram_for_caller(
            fid, drawn_for, skip_within_unit=skip_within_unit)
    finally:
        del gen.get_call_description
    name = gen.get_function_name
    now_ctx = [real._build_call_context(a, b, name, world.now.functions) for a, b in calls]
    moved = [ctx != real._build_call_context(a, b, name, world.then.functions)
             for ctx, (a, b) in zip(now_ctx, calls)]
    if not any(moved):
        return None
    aligned = (len(bullets) == len(stored)
               and all(b == st for b, st in zip(bullets, stored) if not b.startswith("\x00")))
    out: List[Optional[str]] = []
    for pos, bullet in enumerate(bullets):
        if not bullet.startswith("\x00"):
            out.append(bullet)
            continue
        i = int(bullet[1:])
        a, b = calls[i]
        if aligned and not moved[i] and stored[pos]:
            # Its prompt did not move: its words stay, and the cache learns them under the prompt
            # they were written from, so a later Phase 3 keeps them too.
            if now_ctx[i]:
                _cached_desc(world.config, real.cache_material(now_ctx[i]),
                             lambda text=stored[pos]: text)
            out.append(stored[pos])
            continue
        ctx = real._build_call_context(a, b, name, world.live_functions)
        if not ctx:
            # Neither end has a description: the view writes "<caller> calls <callee>".
            out.append(real.get_call_description(a, b, name, world.live_functions))
        else:
            out.append(real._query_llm_for_description(ctx) or None)
    return out


# ---------------------------------------------------------------------------
# storing -- through the save's writers, one text per transaction
# ---------------------------------------------------------------------------
class _Writer:
    """Stores a rewritten text where Phase 2 or 3 stores it, through the save's writers, in a
    transaction of its own under the version's save lock -- checking again, inside it, that no
    reviewer corrected the text meanwhile (REQ-CS-03) -- and retires its queue entry with it.
    `finish` re-derives the SWE.4 specs of the components whose descriptions moved, as a save
    does, and stamps the copies brought up to date."""

    def __init__(self, engine, version_id: str, world: _World):
        self.engine, self.version_id, self.world = engine, version_id, world
        self._stamps: Set[Tuple[str, str]] = set()
        self._swe4: Set[str] = set()

    def _txn(self, kind: str, key: str, write: Callable[[Any], None]) -> bool:
        from review import cascade
        from review.override_service import _serialize_saves
        with self.engine.begin() as cx:
            _serialize_saves(cx, self.version_id)
            if _is_human(_overridden(cx, self.version_id, key), kind, key):
                cascade.clear(cx, self.version_id, kind, key)
                return False
            write(cx)
            cascade.clear(cx, self.version_id, kind, key)
        return True

    def retire(self, kind: str, key: str) -> None:
        from review import cascade
        with self.engine.begin() as cx:
            cascade.clear(cx, self.version_id, kind, key)

    def description(self, key: str, text: str, artifact: str) -> bool:
        from core import model_store as ms
        from review import rerender

        def write(cx):
            ms.set_entity_field(cx, self.version_id, key, "description", text, (artifact,))
            if rerender.patch_interface_tables(cx, self.version_id, key, text):
                self._stamps.add(("interfaceTables", key.split("|", 1)[0]))
        if not self._txn(slot.DESCRIPTION, slot.for_entity(slot.DESCRIPTION, key), write):
            return False
        live = self.world.live_functions if artifact == "function" else self.world.live_globals
        live[key] = {**live.get(key, {}), "description": text}
        self._swe4.add(key.split("|", 1)[0])
        return True

    def unit(self, key: str, unit_key: str, text: str) -> bool:
        from core import model_store as ms
        return self._txn(slot.UNIT_DESCRIPTION, key,
                         lambda cx: ms.set_unit_description(cx, self.version_id, unit_key, text))

    def names(self, fid: str, input_name: str, output_name: str) -> bool:
        """Both names, keeping whichever a reviewer corrected."""
        from core import model_store as ms
        from review import cascade
        from review.override_service import _serialize_saves
        f = self.world.live_functions.get(fid) or {}
        with self.engine.begin() as cx:
            _serialize_saves(cx, self.version_id)
            human = _overridden(cx, self.version_id, fid)
            for kind, field, value in ((slot.INPUT_NAME, "inputName", input_name),
                                       (slot.OUTPUT_NAME, "outputName", output_name)):
                if value and (kind, fid) not in human and value != f.get(field):
                    ms.set_entity_field(cx, self.version_id, fid, field, value, ("function",))
            cascade.clear(cx, self.version_id, slot.INPUT_NAME, fid)
        return True

    def row(self, key: str, parts: Dict[str, str], text: str) -> bool:
        from review import rerender

        def write(cx):
            for rel_path, content, _row in rerender.find_behaviour_rows(
                    cx, self.version_id, parts["function_id"], parts["external_caller_id"]):
                rerender.write_behaviour_row(cx, self.version_id, rel_path, content, key, text)
            self._stamps.add(("behaviourDiagram", parts["function_id"].split("|", 1)[0]))
        return self._txn(slot.BEHAVIOUR_DESCRIPTION, key, write)

    def finish(self) -> None:
        if not (self._stamps or self._swe4):
            return
        from review import swe4_rederive
        from review.export_guard import stamp_saved
        now = datetime.datetime.now(datetime.timezone.utc)
        with self.engine.begin() as cx:
            pairs = set(self._stamps)
            for comp in sorted(self._swe4):
                views = swe4_rederive.rederive(
                    cx, self.version_id, comp,
                    lambda: swe4_rederive.model_of(None, cx, self.version_id))
                pairs |= {(view, comp) for view in views or ()}
            stamp_saved(cx, self.version_id, sorted(pairs), now)


def _flush_caches(config: Dict[str, Any]) -> None:
    """Land the description cache's buffered writes now -- not at the process's exit, which a
    long-lived process does not reach for days."""
    try:
        from llm_enrichment import _aux_desc_cache
        _aux_desc_cache(config).flush()
    except Exception:                               # noqa: BLE001 -- a lost entry, never output
        pass


# ---------------------------------------------------------------------------
# reading the review state
# ---------------------------------------------------------------------------
def _component(kind: str, key: str) -> str:
    """The component a queued text belongs to, in `export_guard.component_id` form: the first
    part of its key's id."""
    from review.export_guard import component_id
    if kind == FLOWCHART_LABELS:
        return component_id((key or "").split("|", 1)[0])
    from review.derive import component_of
    try:
        return component_id(component_of(kind, key))
    except slot.SlotKeyError:
        return ""


def _overridden(conn, version_id: str, key: Optional[str] = None) -> Set[Tuple[str, str]]:
    """`{(kind, key)}` of the corrections in force -- of one key when given."""
    t = s.text_overrides
    q = select(t.c.slot_kind, t.c.slot_key).where(t.c.version_id == version_id,
                                                  t.c.is_orphaned.is_(False))
    if key is not None:
        q = q.where(t.c.slot_key == key)
    return {(r.slot_kind, r.slot_key) for r in conn.execute(q)}


def _is_human(human: Set[Tuple[str, str]], kind: str, key: str) -> bool:
    """A reviewer's own text, which a rewrite never replaces (REQ-CS-03). The names entry stands
    for both names; a chart keeps each corrected label -- Phase 3 puts them back over its new
    ones -- so its entry is never a reviewer's."""
    if kind == FLOWCHART_LABELS:
        return False
    if kind == slot.INPUT_NAME:
        return all((k, key) in human for k in (slot.INPUT_NAME, slot.OUTPUT_NAME))
    return (kind, key) in human


def _stored_charts(conn, version_id: str) -> Tuple[Set[str], Set[str]]:
    """The function keys -- and, for charts stored before they carried one, the names -- of every
    chart in the version's stored output."""
    from review import rerender
    keys: Set[str] = set()
    names: Set[str] = set()
    for r in rerender.output_rows(conn, version_id, rerender.FLOWCHARTS):
        try:
            arr = json.loads(r.content or "[]")
        except ValueError:
            continue
        for e in arr if isinstance(arr, list) else ():
            if isinstance(e, dict):
                if e.get("functionKey"):
                    keys.add(e["functionKey"])
                elif e.get("name"):
                    names.add(e["name"])
    return keys, names


def _approved_components(conn, version_id: str) -> Set[str]:
    """The components with an approved document in the version: a correction there is refused
    (`review_workflow.refuse_if_approved`), and so is a rewrite."""
    from review.export_guard import component_id
    d = s.documents
    return {component_id(r.component) for r in conn.execute(
        select(d.c.component).where(d.c.version_id == version_id, d.c.status == "approved"))
            if r.component}


# ---------------------------------------------------------------------------
# imports and inputs
# ---------------------------------------------------------------------------
def _ensure_paths() -> None:
    """`engine/` and `engine/flowchart/` on the path: the flowchart package imports its own
    modules flat (as `review.redraw` arranges)."""
    eng = os.path.join(_REPO_ROOT, "engine")
    for p in (eng, os.path.join(eng, "flowchart")):
        if p not in sys.path:
            sys.path.insert(0, p)


def _model_deriver():
    """`model_deriver`, imported as a module. It is a phase script: on import it reads the run
    identity off the command line (`apply_cli_run_context`) -- handed this process's own arguments
    it would take the caller's flags for its own -- so it is imported with none."""
    if "model_deriver" in sys.modules:
        return sys.modules["model_deriver"]
    _ensure_paths()
    saved = sys.argv
    sys.argv = [saved[0] if saved else "rewrite"]
    try:
        import model_deriver
    finally:
        sys.argv = saved
    return model_deriver


def read_config(path: str) -> Dict[str, Any]:
    """A run config file, read as a run reads it (`core.config.load_config`)."""
    from core.config import _strip_json_comments, _strip_trailing_commas
    with open(path, encoding="utf-8") as fh:
        return json.loads(_strip_trailing_commas(_strip_json_comments(fh.read())))


# ---------------------------------------------------------------------------
# the update's step, and a process of its own for a caller that serves every project
# ---------------------------------------------------------------------------
def run_step(version_id: str, project_id: str, components: Optional[List[str]], *,
             config: Dict[str, Any], base_path: str, labels_request: Optional[str],
             log: Callable[[str], None] = print) -> Result:
    """The update's step: take this run's identity, rewrite, and leave the charts for Phase 3 at
    `labels_request` (`write_labels_request`). For a process that is this one run --
    `analyzer.py`, or `main` below for the API, whose own process serves every project."""
    from core.db import get_engine, is_database_configured
    from core.run_context import set_run_context
    if labels_request:
        write_labels_request(labels_request, ())
    if not is_database_configured():
        return NOTHING
    engine = get_engine()
    if not queued(engine, version_id, components):
        # Nothing to rewrite -- every generation's `export` and `resume`: the run is left as it
        # was, its identity included.
        return NOTHING
    set_run_context(version=version_id, project=project_id)
    result = rewrite_queued(engine, version_id, components, config=config,
                            base_path=base_path, log=log)
    if labels_request:
        write_labels_request(labels_request, result.charts)
    return result


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Rewrite the texts written from corrected ones, for "
                                            "the components a Word-file update writes.")
    p.add_argument("--version-id", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--config", required=True, help="the version's run config")
    p.add_argument("--source", required=True, help="the version's source checkout")
    p.add_argument("--scope-type", default="project",
                   choices=("project", "layer", "group", "component"))
    p.add_argument("--scope-name", action="append", default=[],
                   help="a layer, group or component the update writes (repeatable)")
    p.add_argument("--labels-request", default=None,
                   help="where to leave the charts for run.py --rewrite-labels")
    a = p.parse_args(argv)
    config = read_config(a.config)
    run_step(a.version_id, a.project_id,
             scope_components(config, {"type": a.scope_type, "names": a.scope_name}),
             config=config, base_path=a.source, labels_request=a.labels_request)
    return 0


if __name__ == "__main__":
    sys.exit(main())
