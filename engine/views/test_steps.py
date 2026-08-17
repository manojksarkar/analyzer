"""CFG -> numbered Test Steps (SWE.4).

Turns the control-flow graph the flowchart engine emits into the nested,
numbered transcription docs/spec/SWE4_WIKI.md specifies:

    1) Issue function FtlLookup with inputs lba, mode.
    2) Check whether lba is a valid LBA.
       2.1) True: continue to step 3.
       2.2) False: return -1.
    3) Return 0.

Structure is recovered with post-dominators: a decision's branches run until the
node that every path through it reaches (its immediate post-dominator), and that
node is where the parent block resumes. Loops fall out of the same rule -- a
LOOP_HEAD's "No" edge already points at the continuation, so only the body nests.

Deterministic: no LLM here. Node wording is whatever the flowchart engine wrote
(its LLM labels when enabled, raw source otherwise).
"""
import json
import os
import re

from utils import log

# Edge labels the CFG uses for the two legs of a decision, mapped to the wording
# the spec asks for. Anything else (switch `case 1`, `default`) passes through.
_TRUE_LABELS = {"yes", "true"}
_FALSE_LABELS = {"no", "false"}

_TERMINAL_TYPES = {"RETURN", "BREAK", "CONTINUE"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_cfgs(output_dir):
    """{functionKey: cfg} for every flowchart JSON under <output_dir>/flowcharts.

    Returns an empty dict when the flowcharts view has not run -- callers treat
    a missing CFG as "no steps", never as an error.
    """
    fc_dir = os.path.join(output_dir, "flowcharts")
    if not os.path.isdir(fc_dir):
        return {}
    cfgs = {}
    for name in sorted(os.listdir(fc_dir)):
        if not name.endswith(".json") or name == "_summary.json":
            continue
        try:
            with open(os.path.join(fc_dir, name), "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (OSError, ValueError):
            continue
        for entry in entries or []:
            cfg = entry.get("cfg")
            if cfg and entry.get("functionKey"):
                cfgs[entry["functionKey"]] = cfg
    return cfgs


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _index(cfg):
    nodes = {n["id"]: n for n in cfg.get("nodes", [])}
    succ = {nid: [] for nid in nodes}
    for e in cfg.get("edges", []):
        if e.get("source") in succ and e.get("target") in nodes:
            succ[e["source"]].append((e["target"], e.get("label")))
    return nodes, succ


def _post_dominators(nodes, succ, exits):
    """pdom[n] = every node on every path from n to an exit (including n)."""
    all_ids = set(nodes)
    pdom = {n: set(all_ids) for n in all_ids}
    for x in exits:
        if x in pdom:
            pdom[x] = {x}
    changed, guard = True, 0
    while changed and guard < 1000:
        changed, guard = False, guard + 1
        for n in all_ids:
            if n in exits:
                continue
            targets = [t for t, _ in succ.get(n, [])]
            if not targets:
                continue
            new = set(all_ids)
            for t in targets:
                new &= pdom[t]
            new = new | {n}
            if new != pdom[n]:
                pdom[n], changed = new, True
    return pdom


def _ipdom(nid, pdom):
    """Nearest strict post-dominator: of all nodes that post-dominate `nid`,
    the one that itself post-dominates the fewest -- i.e. the closest."""
    strict = pdom.get(nid, set()) - {nid}
    if not strict:
        return None
    return max(strict, key=lambda m: (len(pdom.get(m, ())), m))


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

def _clean(text):
    """Strip the flowchart engine's rendering markup from a node label.

    Labels are written for Graphviz, so they can carry `<br/>` line breaks and a
    trailing `Calls: a(), b()` annotation for the tooltip. Neither belongs in a
    test step -- the calls are already named in the step text and in the
    Precondition.
    """
    t = (text or "").replace("<br/>", " ").replace("<br>", " ")
    head = t.split("Calls:")[0]
    return " ".join(head.split()).strip()


def _sentence(text):
    t = _clean(text).rstrip("?").strip().rstrip(";").strip()
    if not t:
        return ""
    return t if t.endswith(".") else t + "."


def _strip_prefix(label, *prefixes):
    t = _clean(label)
    for p in prefixes:
        if t.lower().startswith(p.lower()):
            return t[len(p):].strip()
    return t


def _entry_text(spec):
    """Step 1: issue the function under test with its inputs."""
    name = spec.get("name", "the function")
    params = [p.get("name", "") for p in (spec.get("precondition") or {}).get("parameters", [])]
    params = [p for p in params if p]
    if not params:
        return f"Issue function {name} with input VOID."
    return f"Issue function {name} with inputs {', '.join(params)}."


def _mocks_called(node, mock_names):
    """Mock functions this node calls, in the order they appear in its source."""
    raw = node.get("rawCode") or ""
    hits = [m for m in mock_names if m + "(" in raw]
    return sorted(set(hits), key=lambda m: raw.index(m + "("))


def _node_text(node, spec, mock_names, is_entry, ctx=None):
    ntype = node.get("type", "")
    label = node.get("label") or node.get("rawCode") or ""

    if is_entry or ntype == "START":
        return _entry_text(spec)
    if ntype == "BREAK":
        # The CFG labels every break "Exit loop"; inside a switch that is wrong.
        return "Exit the switch." if ctx == "switch" else "Exit the loop."
    if ntype == "DECISION":
        base = _sentence("Check whether " + _strip_prefix(label, "Check:", "Check"))
    elif ntype == "LOOP_HEAD":
        base = _sentence("Repeat " + _strip_prefix(label, "Loop:", "Loop"))
    elif ntype == "SWITCH_HEAD":
        base = _sentence("Select on " + _strip_prefix(label, "Switch on:", "Switch on", "Switch"))
    else:
        base = _sentence(label)

    called = _mocks_called(node, mock_names)
    if called:
        listed = ", ".join(called)
        prefix = f"Expect mock function {listed}"
        return f"{prefix}; {base[0].lower() + base[1:]}" if base else _sentence(prefix)
    return base


def _norm(text):
    """Whitespace/case-insensitive form, for asking whether two renderings of the
    same return say the same thing."""
    return re.sub(r"\s+", "", (text or "")).lower().rstrip(".")


def _writes(raw, name):
    """True when `raw` assigns to `name` — `x = `, `x += `, `x++`, `++x`, `x[i] = `,
    `*x = `. A plain read of the same name does not count, so a global that is
    read here and written elsewhere is only credited to the step that writes it.
    """
    if not raw or not name:
        return False
    n = re.escape(name)
    assign = rf"\*?\b{n}\b\s*(?:\[[^\]]*\]|\.[A-Za-z_]\w*|->[A-Za-z_]\w*)?\s*" \
             rf"(?:\+\+|--|(?:[+\-*/%|&^]|<<|>>)?=(?!=))"
    return bool(re.search(assign, raw) or re.search(rf"(?:\+\+|--)\s*\b{n}\b", raw))


def _leg_label(edge_label):
    """'Yes'/'No' -> 'True'/'False'; switch labels pass through unchanged."""
    lab = (edge_label or "").strip()
    low = lab.lower()
    if low in _TRUE_LABELS:
        return "True"
    if low in _FALSE_LABELS:
        return "False"
    return lab or "Otherwise"


# ---------------------------------------------------------------------------
# Walk
# ---------------------------------------------------------------------------

class _Walker:
    def __init__(self, cfg, spec, mock_names):
        self.nodes, self.succ = _index(cfg)
        self.exits = set(cfg.get("exits") or [])
        self.pdom = _post_dominators(self.nodes, self.succ, self.exits)
        self.spec = spec
        self.mock_names = mock_names
        self.entry = cfg.get("entry")
        self.steps = []      # flat, each {number, text, nodeId, type}
        self.returns = []    # {step, text} -- one per RETURN, for Expected Results
        # name -> [step numbers that assign it], for the written globals and
        # out-parameters Expected Results asserts.
        exp = (spec or {}).get("expected") or {}
        self.written_names = [g.get("name", "") for g in exp.get("globals") or []] + \
                             [o.get("name", "") for o in exp.get("outParameters") or []]
        self.write_steps = {}

    # -- emitting ----------------------------------------------------------
    def _add(self, prefix, idx, node, text):
        number = ".".join(str(x) for x in (prefix + [idx]))
        self.steps.append({"number": number, "text": text,
                           "nodeId": node.get("id", ""), "type": node.get("type", "")})
        raw = node.get("rawCode") or ""
        for name in self.written_names:
            if name and _writes(raw, name):
                self.write_steps.setdefault(name, []).append(number)
        if node.get("type") == "RETURN":
            expr = _strip_prefix(node.get("label") or node.get("rawCode") or "",
                                 "Return", "return").strip().rstrip(";").strip()
            # The wording above is the readable description. Carry the source
            # expression next to it: a generated label paraphrases and can name
            # values the code never uses, and a tester needs something exact to
            # check against. Omitted when the wording already IS the source.
            source = _strip_prefix(node.get("rawCode") or "",
                                   "Return", "return").strip().rstrip(";").strip()
            text = f"Successfully returned {expr}" if expr else "Successfully returned"
            if source and _norm(source) != _norm(expr):
                text = f"{text} [{source}]"
            self.returns.append({"step": number, "expression": expr,
                                 "source": source, "text": text})
        return number

    def _branch_targets(self, nid, join):
        """Outgoing edges that actually open a nested block (the join itself is
        the continuation, not a branch)."""
        return [(t, lab) for t, lab in self.succ.get(nid, []) if t != join]

    def walk(self, nid, stop, prefix, seen=None, ctx=None):
        """Emit the block starting at `nid`, stopping before `stop`.

        `ctx` is the enclosing construct ("switch" or "loop"), which only
        `break` needs in order to name what it exits.
        """
        seen = set() if seen is None else seen
        idx = 0
        while nid and nid != stop and nid not in self.exits:
            if nid in seen:            # back edge -- the loop body already ran
                return
            seen.add(nid)
            node = self.nodes.get(nid)
            if node is None:
                return
            ntype = node.get("type", "")
            is_entry = nid == self.entry

            if ntype in ("DECISION", "LOOP_HEAD", "SWITCH_HEAD"):
                idx += 1
                number = self._add(prefix, idx, node,
                                   _node_text(node, self.spec, self.mock_names, is_entry, ctx))
                join = _ipdom(nid, self.pdom)
                legs = self._branch_targets(nid, join)
                leg_ctx = ({"SWITCH_HEAD": "switch", "LOOP_HEAD": "loop"}
                           .get(ntype, ctx))
                for leg_i, (target, lab) in enumerate(legs, start=1):
                    self._emit_leg(prefix + [idx], leg_i, target, join,
                                   _leg_label(lab), set(seen), leg_ctx)
                if not legs:
                    return
                nid = join
                continue

            idx += 1
            self._add(prefix, idx, node,
                      _node_text(node, self.spec, self.mock_names, is_entry, ctx))
            if ntype in _TERMINAL_TYPES:
                return                 # control leaves this block
            nxt = [t for t, _ in self.succ.get(nid, [])]
            nid = nxt[0] if nxt else None

    def _emit_leg(self, prefix, leg_i, target, join, leg_label, seen, ctx=None):
        """One leg of a decision/switch: `2.1) True: ...`.

        A single-step leg is written inline after the label; a multi-step leg
        gets the label on its own line and nests its steps beneath it.
        """
        before = len(self.steps)
        sub = _Walker.__new__(_Walker)
        sub.__dict__.update(self.__dict__)
        sub.steps, sub.returns = [], []
        sub.walk(target, join, prefix + [leg_i], seen, ctx)

        number = ".".join(str(x) for x in (prefix + [leg_i]))
        if len(sub.steps) == 1:
            only = sub.steps[0]
            self.steps.append({"number": number, "text": f"{leg_label}: {only['text']}",
                               "nodeId": only["nodeId"], "type": only["type"]})
            # the lone step was folded into the leg label, so any write it
            # recorded now belongs to the leg's number
            for name, nums in self.write_steps.items():
                self.write_steps[name] = [number if n == only["number"] else n
                                          for n in nums]
            for r in sub.returns:
                r["step"] = number
            self.returns.extend(sub.returns)
            return
        if not sub.steps:
            self.steps.append({"number": number,
                               "text": f"{leg_label}: continue.", "nodeId": "", "type": ""})
            return
        self.steps.append({"number": number, "text": f"{leg_label}:",
                           "nodeId": "", "type": "LEG"})
        self.steps.extend(sub.steps)
        self.returns.extend(sub.returns)
        del before


def build_steps(cfg, spec, mock_names=()):
    """(steps, returns, write_steps) for one function.

    `write_steps` maps a written global / out-parameter name to the step numbers
    that assign it, so Expected Results can say which step wrote it. Empty when
    there is no CFG.
    """
    if not cfg or not cfg.get("entry"):
        return [], [], {}
    names = [m[:-2] if m.endswith("()") else m for m in (mock_names or ())]
    w = _Walker(cfg, spec, names)
    w.walk(cfg["entry"], None, [])
    return w.steps, w.returns, w.write_steps


def attach(test_specs, output_dir):
    """Fill `testSteps` and `expected.returns` on every spec that has a CFG.

    Best-effort: a spec whose function has no flowchart keeps its empty lists,
    so the document still renders.
    """
    cfgs = load_cfgs(output_dir)
    if not cfgs:
        log("no flowchart CFGs under %s - Test Steps left empty"
            % os.path.join(output_dir, "flowcharts"), component="testSpecs")
        return 0
    filled = 0
    for key, unit in test_specs.items():
        if key == "unitNames" or not isinstance(unit, dict):
            continue
        for spec in unit.get("functions", []):
            cfg = cfgs.get(spec.get("functionId"))
            if not cfg:
                continue
            steps, returns, write_steps = build_steps(
                cfg, spec, (spec.get("precondition") or {}).get("mockFunctions", ()))
            if steps:
                spec["testSteps"] = steps
                spec["expected"]["returns"] = returns
                # tell each written global / out-parameter which step assigns it
                for entry in (spec["expected"].get("globals") or []) + \
                             (spec["expected"].get("outParameters") or []):
                    nums = write_steps.get(entry.get("name"))
                    if nums:
                        entry["steps"] = nums
                filled += 1
    return filled
