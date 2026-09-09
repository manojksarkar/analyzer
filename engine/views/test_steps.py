"""CFG -> numbered Test Steps (SWE.4).

Turns the control-flow graph the flowchart engine emits into the nested,
numbered transcription docs/spec/SWE4_WIKI.md specifies:

    1) Issue function FtlLookup with inputs lba, mode.
    2) Check whether lba is a valid LBA.
       2.a) True: continue to step 3.
       2.b) False: return -1.
    3) Return 0.

Levels alternate numeric / alphabetic (`4`, `4.a`, `4.a.3`, `4.a.3.b`) so a deeply
nested transcription stays readable where `4.1.3.2` does not.

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

def _level(idx, depth):
    """One level of a step number. Levels alternate numeric / alphabetic --
    `4`, `4.a`, `4.a.3`, `4.a.3.b` -- which keeps a deep transcription readable
    where `4.1.3.2` does not. Alphabetic levels carry past `z` the spreadsheet
    way (`z`, `aa`, `ab`), so a block with 27 branches still numbers."""
    if depth % 2 == 0:
        return str(idx)
    out, n = "", idx
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("a") + rem) + out
    return out or "a"


def _number(parts):
    """Join one step number. `number` stays the single field every consumer
    reads (`expected.returns[].step`, `globals[].steps`, ut_export's `atStep`),
    so changing the format here changes every cross-reference with it."""
    return ".".join(_level(v, d) for d, v in enumerate(parts))


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


def _spliced_called(node, splice):
    """Executing cross-unit callees this node calls, in source order.

    Same matcher as `_mocks_called`, different verdict: a mock is named and left
    alone, a spliced callee is named *and its body is walked in*.
    """
    if not splice:
        return []
    raw = node.get("rawCode") or ""
    hits = [n for n in splice if n + "(" in raw]
    return sorted(set(hits), key=lambda m: raw.index(m + "("))


def _call_args(raw, name):
    """The top-level argument expressions of the FIRST `name(...)` call in `raw`.

    Paren-balanced rather than split on commas, so a nested call
    (`Foo(a, Bar(b, c))`) yields two arguments, not three. Returns [] when the
    call is not found or its parentheses do not close inside this node's text --
    a node holds whole statements, so an unbalanced tail means the match was a
    substring of some other name and should be ignored.
    """
    i = raw.find(name + "(")
    if i < 0:
        return []
    i += len(name)
    depth, start, args = 0, i + 1, []
    for j in range(i, len(raw)):
        c = raw[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append(raw[start:j])
                return [a.strip() for a in args]
        elif c == "," and depth == 1:
            args.append(raw[start:j])
            start = j + 1
    return []


def _statements(raw):
    """Split a node's source into statements, on top-level semicolons only.

    A node holds a RUN of statements (the flowchart engine groups up to five), so
    wording has to be derived per statement, not for the node as a whole. A
    semicolon inside parentheses -- `for (i = 0; i < n; i++)` -- does not split,
    or a loop header would arrive as three fragments.
    """
    out, depth, cur = [], 0, ""
    for c in raw or "":
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == ";" and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += c
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def _split_args(argstr):
    """Top-level comma split, so `Bar(b, c)` stays one argument."""
    out, depth, cur = [], 0, ""
    for c in argstr or "":
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += c
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def _is_out_param_type(t):
    """`T*`/`T&` is written through, `const T*` is read. Mirrors
    `test_specs._is_out_parameter`, which decides the same question for the
    function under test; a function pointer is a callback, not an output."""
    t = t or ""
    if "*" not in t and "&" not in t:
        return False
    if "(*" in t.replace(" ", ""):
        return False
    return "const" not in t


# ---------------------------------------------------------------------------
# Statement -> English
# ---------------------------------------------------------------------------

# Group `lhs` is the assignment target; the declared type falls away because
# `_lhs_name` keeps only the last identifier. `==`, `!=`, `<=`, `>=` and the
# compound operators are excluded, so a comparison is never read as assignment.
_ASSIGN_RE = re.compile(r"^(?P<lhs>[\w\s*&\[\].>-]+?)(?<![=!<>+\-*/%|&^])=(?!=)(?P<rhs>.+)$", re.S)
_CALL_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*\((?P<args>.*)\)$", re.S)
_INCDEC_RE = re.compile(r"^(?:(?P<pre>\+\+|--)\s*(?P<a>[\w.>\[\]-]+)"
                        r"|(?P<b>[\w.>\[\]-]+)\s*(?P<post>\+\+|--))$")
_COMPOUND_RE = re.compile(r"^(?P<lhs>[\w.>\[\]-]+)\s*(?P<op>[+\-*/%|&^]|<<|>>)=(?P<rhs>.+)$", re.S)

# A statement that is nothing but one call: `HilNotify(ERR_RANGE);`.
_CALL_STMT_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\(.*\)\s*;?\s*$", re.S)

_BRANCH_TYPES = ("DECISION", "LOOP_HEAD", "SWITCH_HEAD")

# `goto exit;`. Group 1 is the label, which leads the wording: a tester reads
# `goto exit` in the code and looks for "exit" in the steps.
_GOTO_RE = re.compile(r"^\s*goto\b\s*(\w*)", re.I)

# A statement opening with one of these is control flow, not something to
# describe: the CFG has already given it its own node type. Without the guard
# `for (int i = 0; ...)` is read as a call and described "Call function for()".
_KEYWORDS = {"if", "else", "for", "while", "do", "switch", "case", "default",
             "return", "goto", "break", "continue", "sizeof"}

# `!= 0` -> "is not equal to 0". Longest first, so `>=` never matches as `>`.
_COMPARISONS = (("!=", "is not equal to"), ("==", "is equal to"),
                (">=", "is greater than or equal to"), ("<=", "is less than or equal to"),
                (">", "is greater than"), ("<", "is less than"))


def _lhs_name(lhs):
    """`int clipped` -> `clipped`, `*half` -> `half`. The declared type and the
    dereference are noise to a tester, who matches on the name."""
    t = (lhs or "").strip()
    parts = t.replace("*", " ").replace("&", " ").split()
    return parts[-1] if parts else t


def _describe(stmt):
    """One statement as an English sentence, or None when no rule fits.

    None matters: the caller then keeps the flowchart's own label rather than
    inventing wording for a shape this does not understand.
    """
    stmt = " ".join((stmt or "").split())
    if not stmt:
        return None
    if stmt.split("(")[0].strip().split(" ")[0] in _KEYWORDS:
        return None
    m = _INCDEC_RE.match(stmt)
    if m:
        name = m.group("a") or m.group("b")
        op = m.group("pre") or m.group("post")
        return ("Increment" if op == "++" else "Decrement") + f" {name} by one"
    m = _COMPOUND_RE.match(stmt)
    if m:
        verb = {"+": "Increment", "-": "Decrement"}.get(m.group("op"))
        lhs, rhs = m.group("lhs"), m.group("rhs").strip()
        if verb:
            return f"{verb} {lhs} by {rhs}"
        return f"Set {lhs} to {lhs} {m.group('op')} {rhs}"
    m = _ASSIGN_RE.match(stmt)
    if m:
        lhs, rhs = _lhs_name(m.group("lhs")), m.group("rhs").strip()
        call = _CALL_RE.match(rhs)
        if call:
            args = ", ".join(_split_args(call.group("args")))
            with_args = f" with {args}," if args else ""
            return f"Call function {call.group('name')}(){with_args} storing the result in {lhs}"
        return f"Set {lhs} to {rhs}"
    call = _CALL_RE.match(stmt)
    if call:
        args = ", ".join(_split_args(call.group("args")))
        return f"Call function {call.group('name')}()" + (f" with {args}" if args else "")
    return None


def _comparison(condition, name):
    """The tail of a condition once the mocked call is taken out of it.

    `FilReadPage(i, &e) != 0` -> "is not equal to 0". A bare `if (ready(x))` has
    no operator at all, so the value simply has to be true. The source operator
    is mirrored, never inverted into something friendlier -- get that backwards
    and the True leg sends the tester down the opposite branch.
    """
    cond = " ".join((condition or "").split())
    idx = cond.find(name + "(")
    if idx >= 0:
        args = _call_args(cond, name)
        rendered = "%s(%s)" % (name, ", ".join(args))
        tail = cond[idx:]
        tail = tail.replace(rendered, "", 1) if rendered in tail else ""
        cond = (cond[:idx] + tail).strip()
    cond = cond.strip("() ").strip()
    for op, phrase in _COMPARISONS:
        if cond.startswith(op):
            return ("%s %s" % (phrase, cond[len(op):].strip())).strip()
    return "is true"


def _mock_facts(raw, name, mock_sigs):
    """What one mocked call takes in, hands back, and is assigned to.

      `target`  the variable the call is assigned to -- `int sum = libAdd(a, b);`
      `outputs` arguments the callee writes THROUGH -- `FilReadPage(i, &e)` -> `e`
      `inputs`  the remaining arguments, which the code passes IN

    Keeping `inputs` and `outputs` apart is the point. `&e` is not a value the
    tester supplies, it is the slot the stub fills, so listing it beside `i` as
    something the mock is "called with" would ask for a value that is a result.
    Which side an argument falls on is read off the callee's own signature.
    """
    target = None
    for stmt in _statements(raw):
        if name + "(" not in stmt:
            continue
        m = _ASSIGN_RE.match(" ".join(stmt.split()))
        if m and name + "(" in m.group("rhs"):
            target = _lhs_name(m.group("lhs"))
        break
    sig = mock_sigs.get(name) or []
    inputs, outputs = [], []
    for pos, arg in enumerate(_call_args(raw, name)):
        arg = arg.strip()
        if not arg:
            continue
        param = sig[pos] if pos < len(sig) else None
        if param and _is_out_param_type(param.get("type", "")):
            bare = arg.lstrip("&").strip()
            if re.fullmatch(r"[A-Za-z_]\w*", bare):
                outputs.append(bare)
            continue                 # never an input, whatever it looks like
        inputs.append(arg)
    return {"target": target, "inputs": inputs, "outputs": outputs}


def _with_setting(facts):
    """The ` with a, b, setting c` tail shared by two of the four shapes."""
    tail = ""
    if facts["inputs"]:
        tail += " with " + ", ".join(facts["inputs"])
    if facts["outputs"]:
        tail += ", setting " + ", ".join(facts["outputs"])
    return tail


def _mock_clause(name, facts, kind, condition="", lead=True):
    """One mocked call, in whichever of the four shapes its value calls for.

    The shape follows what the returned value is USED for, because that decides
    whether the tester has anything to fix and what to call it:

      assigned       Update sum by mocking function libAdd()
      is the return  Expect return value from the return of mock function f() with x, y inputs
      picks a branch Derive value to return of mock function f() with i, setting e and check ...
      discarded/void Mock function HilNotify() with ERR_RANGE
    """
    fn = "%s()" % name

    def cap(word):
        return word if lead else word[0].lower() + word[1:]

    if facts["target"]:
        sets = ", ".join([facts["target"]] + facts["outputs"])
        return "%s %s by mocking function %s" % (cap("Update"), sets, fn)
    if kind == "return":
        ins = ", ".join(facts["inputs"])
        tail = " with %s inputs" % ins if ins else ""
        return "%s return value from the return of mock function %s%s" % (cap("Expect"), fn, tail)
    if kind == "branch":
        return "%s value to return of mock function %s%s and check it %s" % (
            cap("Derive"), fn, _with_setting(facts), condition)
    return "%s function %s%s" % (cap("Mock"), fn, _with_setting(facts))


def _mock_sentence(raw, called, mock_sigs, kind="plain", condition=""):
    """The mock clause for one node.

    Several ASSIGNED mocks collapse into one parallel pair of lists, which is the
    client's own wording. That reads correctly only while every mock contributes
    exactly one variable; the moment one does not, the lists would differ in
    length and pair silently wrong, so each mock keeps its own clause instead.
    """
    facts = [(m, _mock_facts(raw, m, mock_sigs)) for m in called]
    if len(facts) > 1 and all(f["target"] and not f["outputs"] for _, f in facts):
        names = ", ".join(f["target"] for _, f in facts)
        fns = ", ".join("%s()" % m for m, _ in facts)
        return "Update %s by mocking function %s" % (names, fns)
    return "; ".join(_mock_clause(m, f, kind, condition, lead=(i == 0))
                     for i, (m, f) in enumerate(facts))


def _plain_text(node, ntype, label, called):
    """A node's own wording, with every statement the mock clause already covers
    left out so nothing is said twice.

    A DECISION / LOOP_HEAD / SWITCH_HEAD carries a condition, not statements, so
    it keeps the flowchart's phrasing. A plain node is described statement by
    statement in source order; a statement `_describe` cannot read falls back to
    the label, which is where the flowchart's own (LLM or raw) text comes in.
    """
    if ntype == "DECISION":
        return _sentence("Check whether " + _strip_prefix(label, "Check:", "Check"))
    if ntype == "LOOP_HEAD":
        return _sentence("Repeat " + _strip_prefix(label, "Loop:", "Loop"))
    if ntype == "SWITCH_HEAD":
        return _sentence("Select on " + _strip_prefix(label, "Switch on:", "Switch on", "Switch"))
    if ntype == "RETURN":
        return _sentence(label)
    stmts = [st for st in _statements(node.get("rawCode") or "")
             if not any(m + "(" in st for m in called)]
    if not stmts:
        # Every statement here is a mocked call, so the mock clause is the step.
        return "" if called else _sentence(label)
    described = [_describe(st) for st in stmts]
    if any(d is None for d in described):
        return _sentence(label)          # a shape this does not understand
    return _sentence("; ".join(described))


def _label_prefix(node):
    """`done: ` when this node is the target of a goto.

    A label takes no node of its own -- the CFG points the name at the labelled
    statement -- so naming it here is what lets a jump be followed in both
    directions. Absent on a CFG stored before the field existed, which simply
    leaves the destination unlabelled.
    """
    name = (node.get("gotoLabel") or "").strip()
    return f"{name}: " if name else ""


def _node_text(node, spec, mock_names, is_entry, ctx=None, splice=None, home_unit=""):
    ntype = node.get("type", "")
    label = node.get("label") or node.get("rawCode") or ""
    raw = node.get("rawCode") or ""

    if is_entry or ntype == "START":
        return _entry_text(spec)
    if ntype == "BREAK":
        # The CFG labels every break "Exit loop"; inside a switch that is wrong.
        return _label_prefix(node) + ("Exit the switch." if ctx == "switch"
                                      else "Exit the loop.")

    called = _mocks_called(node, mock_names)
    base = _plain_text(node, ntype, label, called)

    # A dynamic behaviour spec attributes every cross-unit call to the units on
    # each side; a function spec has no `splice` and reads exactly as before.
    parts = []
    spliced = _spliced_called(node, splice)
    if spliced:
        listed = ", ".join(splice[n]["label"] for n in spliced)
        parts.append(f"{home_unit} calls {listed}" if home_unit else f"Call {listed}")
    if called:
        mock_sigs = {m.get("name"): m.get("parameters") or []
                     for m in ((spec or {}).get("precondition") or {}).get("mocks") or []}
        # What the returned value is USED for picks the wording. A branch head
        # folds its own check into the mock clause, so `base` is dropped there.
        if ntype in _BRANCH_TYPES:
            cond = _strip_prefix(label, "Check:", "Check", "Loop:", "Loop").rstrip("?").strip()
            kind, condition = "branch", _comparison(cond or raw, called[0])
            base = ""
        elif ntype == "RETURN":
            kind, condition = "return", ""
            base = ""
        else:
            kind, condition = "plain", ""
        parts.append(_mock_sentence(raw, called, mock_sigs, kind, condition))
    if not parts:
        return _label_prefix(node) + base
    prefix = _label_prefix(node) + "; ".join(parts)
    if not base:
        return _sentence(prefix)
    # Source order decides whether the MOCK clause or the node's own wording
    # leads: `gErrCount++; HilNotify(ERR);` reads "Increment gErrCount by one;
    # mock function HilNotify() with ERR". A dynamic spec's unit attribution is
    # not a statement and always leads, so it is exempt.
    stmts = _statements(raw)
    first_mock = next((i for i, st in enumerate(stmts)
                       if any(m + "(" in st for m in called)), len(stmts))
    first_plain = next((i for i, st in enumerate(stmts)
                        if not any(m + "(" in st for m in called)), len(stmts))
    if called and not spliced and first_plain < first_mock:
        return f"{base.rstrip('.')}; {prefix[0].lower() + prefix[1:]}."
    return f"{prefix}; {base[0].lower() + base[1:]}"


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
    def __init__(self, cfg, spec, mock_names, splice=None, home_unit="",
                 suppress_entry=False, splice_stack=frozenset()):
        self.nodes, self.succ = _index(cfg)
        self.exits = set(cfg.get("exits") or [])
        self.pdom = _post_dominators(self.nodes, self.succ, self.exits)
        self.spec = spec
        self.mock_names = mock_names
        # short name -> {label, fid, cfg}. Empty for a function spec, which is why
        # nothing below changes its output.
        self.splice = splice or {}
        self.home_unit = home_unit
        # `Issue function <name>` belongs to the spec's own entry, not to a callee
        # body walked in underneath it.
        self.suppress_entry = suppress_entry
        # Function ids already on the splice path, so a cycle between units
        # terminates instead of recursing forever.
        self.splice_stack = splice_stack
        self.entry = cfg.get("entry")
        self.steps = []      # flat, each {number, text, nodeId, type}
        self.returns = []    # {step, text} -- one per RETURN, for Expected Results
        # nodeId -> the step number it was first emitted as, plus the steps whose
        # wording has to name another step (a goto's target, a leg's
        # continuation). Both are resolved after the walk, because a jump points
        # forward. Shared with the per-leg sub-walkers via the __dict__ copy.
        self.number_by_node = {}
        self.jumps = []
        # name -> [step numbers that assign it], for the written globals and
        # out-parameters Expected Results asserts.
        exp = (spec or {}).get("expected") or {}
        self.written_names = [g.get("name", "") for g in exp.get("globals") or []] + \
                             [o.get("name", "") for o in exp.get("outParameters") or []]
        self.write_steps = {}

    # -- emitting ----------------------------------------------------------
    def _add(self, prefix, idx, node, text):
        number = _number(prefix + [idx])
        step = {"number": number, "text": text,
                "nodeId": node.get("id", ""), "type": node.get("type", "")}
        self.steps.append(step)
        self.number_by_node.setdefault(node.get("id", ""), number)
        raw = node.get("rawCode") or ""
        goto = _GOTO_RE.match(raw)
        if goto:
            # The flowchart engine has no GOTO node type: a goto is an ACTION
            # whose single edge is the deferred jump to the label. That edge is
            # the target, and it almost always points forward -- so the step is
            # recorded here and worded once the whole function is numbered.
            targets = [t for t, _ in self.succ.get(node.get("id", ""), [])]
            if targets:
                self.jumps.append({"step": step, "target": targets[0],
                                   "label": goto.group(1), "kind": "goto", "old": text})
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

    def resolve_jumps(self):
        """Word each jump now that every step has a number.

        Only possible after the whole walk: a `goto` almost always points
        forward, and a leg's continuation is numbered by the parent block after
        the leg has been emitted. A target that was never emitted leaves the step
        exactly as it was written.
        """
        pos = {id(st): i for i, st in enumerate(self.steps)}
        for j in self.jumps:
            number = self.number_by_node.get(j["target"])
            if not number:
                continue
            if j["kind"] == "goto":
                # "Go to step 3" printed directly above step 3 reads like a
                # mistake: nothing is skipped, so say so with an honest verb.
                i = pos.get(id(j["step"]))
                adjacent = (i is not None and i + 1 < len(self.steps)
                            and self.steps[i + 1].get("nodeId") == j["target"])
                verb = "Continue to" if adjacent else "Go to"
                where = f"{j['label']} label in step {number}" if j.get("label") \
                    else f"step {number}"
                new = f"{verb} {where}."
            else:
                new = f"continue to step {number}."
            step, old = j["step"], j.get("old") or ""
            # Replace rather than assign: a single-step leg folds the step's text
            # in after its own label ("True: ..."), which has to survive.
            step["text"] = step["text"].replace(old, new) \
                if old and old in step["text"] else new

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
            is_entry = nid == self.entry and not self.suppress_entry

            if ntype in ("DECISION", "LOOP_HEAD", "SWITCH_HEAD"):
                idx += 1
                number = self._add(prefix, idx, node,
                                   _node_text(node, self.spec, self.mock_names, is_entry,
                                              ctx, self.splice, self.home_unit))
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
                      _node_text(node, self.spec, self.mock_names, is_entry, ctx,
                                 self.splice, self.home_unit))
            # Walk the callee's own body in beneath this step. Only on a plain
            # node: a branch head numbers its legs off `prefix + [idx]`, which the
            # spliced steps would collide with, so those are attributed but not
            # descended into.
            for callee in _spliced_called(node, self.splice):
                self._splice_body(callee, prefix + [idx])
            if ntype in _TERMINAL_TYPES:
                return                 # control leaves this block
            nxt = [t for t, _ in self.succ.get(nid, [])]
            nid = nxt[0] if nxt else None

    def _splice_body(self, callee_name, prefix):
        """Nest a cross-unit callee's own control flow under the step that calls it.

        This is what separates a dynamic behaviour spec from a function spec: the
        function spec stubs this callee and stops, so its branches are asserted
        nowhere in this document; here it really runs, so its flowchart is
        transcribed in place and its returns become assertions of this spec.
        """
        info = self.splice.get(callee_name)
        if not info or info["fid"] in self.splice_stack:
            return                     # unknown, ambiguous, or already on the path
        cfg = info.get("cfg") or {}
        entry = cfg.get("entry")
        if not entry:
            return                     # no flowchart for it -- leave the call step alone
        nodes, succ = _index(cfg)
        # Skip the callee's START node: the calling step already says what is being
        # entered, and START would render as "Issue function ...".
        if (nodes.get(entry) or {}).get("type") == "START":
            nxt = [t for t, _ in succ.get(entry, [])]
            entry = nxt[0] if nxt else None
            if not entry:
                return
        sub = _Walker(cfg, self.spec, self.mock_names, self.splice,
                      info.get("unitName", ""), suppress_entry=True,
                      splice_stack=self.splice_stack | {info["fid"]})
        sub.walk(entry, None, prefix)
        self.steps.extend(sub.steps)
        self.returns.extend(sub.returns)
        for name, nums in sub.write_steps.items():
            self.write_steps.setdefault(name, []).extend(nums)

    def _emit_leg(self, prefix, leg_i, target, join, leg_label, seen, ctx=None):
        """One leg of a decision/switch: `2.a) True: ...`.

        A single-step leg is written inline after the label; a multi-step leg
        gets the label on its own line and nests its steps beneath it.
        """
        before = len(self.steps)
        sub = _Walker.__new__(_Walker)
        sub.__dict__.update(self.__dict__)
        sub.steps, sub.returns = [], []
        sub.walk(target, join, prefix + [leg_i], seen, ctx)

        number = _number(prefix + [leg_i])
        if len(sub.steps) == 1:
            only = sub.steps[0]
            # Folded in place, not copied: a jump recorded against this step holds
            # a reference to the dict, and the node keeps the number it now shows.
            only["number"] = number
            only["text"] = f"{leg_label}: {only['text']}"
            self.steps.append(only)
            if only["nodeId"]:
                self.number_by_node[only["nodeId"]] = number
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
            step = {"number": number, "text": f"{leg_label}: continue.",
                    "nodeId": "", "type": ""}
            self.steps.append(step)
            # The block resumes at the join; say which step that is.
            self.jumps.append({"step": step, "target": join, "kind": "leg",
                               "old": "continue."})
            return
        self.steps.append({"number": number, "text": f"{leg_label}:",
                           "nodeId": "", "type": "LEG"})
        self.steps.extend(sub.steps)
        self.returns.extend(sub.returns)
        del before


def build_steps(cfg, spec, mock_names=(), splice=None, home_unit=""):
    """(steps, returns, write_steps) for one function.

    `write_steps` maps a written global / out-parameter name to the step numbers
    that assign it, so Expected Results can say which step wrote it. Empty when
    there is no CFG.

    `splice` is supplied only by a dynamic behaviour spec: short name ->
    {label, fid, cfg} for each executing cross-unit callee, whose body is walked
    in beneath the step that calls it. Absent for a function spec, which
    therefore renders exactly as it did before.
    """
    if not cfg or not cfg.get("entry"):
        return [], [], {}
    names = [m[:-2] if m.endswith("()") else m for m in (mock_names or ())]
    w = _Walker(cfg, spec, names, splice, home_unit)
    w.walk(cfg["entry"], None, [])
    w.resolve_jumps()
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


def _splice_map(spec, cfgs, functions_data, unit_of, unit_names):
    """short name -> {label, fid, cfg} for the callees whose bodies run here.

    Keyed by short name because that is what the node matcher can see in the
    source (`sp.normalize(raw)` carries `normalize`, not the qualified name).
    That makes collisions possible, and a collision would splice the WRONG body
    into the spec -- a far worse failure than a missing splice. So a short name
    claimed by more than one executing callee is dropped: the call is still
    named in the step, it is simply not descended into.
    """
    by_name = {}
    for fid in spec.get("executingFunctionIds") or []:
        if unit_of.get(fid) == spec.get("unitKey"):
            continue                    # same unit: not a cross-unit interaction
        func = functions_data.get(fid) or {}
        qn = func.get("qualifiedName", "")
        name = (qn.split("::")[-1]).strip()
        if not name:
            continue
        unit_key = unit_of.get(fid, "")
        unit_name = unit_names.get(unit_key, unit_key)
        by_name.setdefault(name, []).append(
            {"label": "%s.%s" % (unit_name, qn or name), "fid": fid,
             "unitName": unit_name, "cfg": cfgs.get(fid)})
    return {name: entries[0] for name, entries in by_name.items()
            if len(entries) == 1}


def attach_dynamic(dynamic, output_dir, functions_data, unit_of, unit_names):
    """Fill `testSteps` and `expected.returns` on every dynamic behaviour spec.

    Same CFG pass as `attach`, with one difference: an executing cross-unit
    callee has its own flowchart walked in under the calling step, so the
    interaction reads as one flow instead of stopping at a stub.
    """
    if not dynamic:
        return 0
    cfgs = load_cfgs(output_dir)
    if not cfgs:
        return 0
    filled = 0
    for specs in dynamic.values():
        for spec in specs:
            cfg = cfgs.get(spec.get("functionId"))
            if not cfg:
                continue
            splice = _splice_map(spec, cfgs, functions_data, unit_of, unit_names)
            steps, returns, write_steps = build_steps(
                cfg, spec, (spec.get("precondition") or {}).get("mockFunctions", ()),
                splice, spec.get("unitName", ""))
            if not steps:
                continue
            spec["testSteps"] = steps
            spec["expected"]["returns"] = returns
            for entry in (spec["expected"].get("globals") or []) + \
                         (spec["expected"].get("outParameters") or []):
                nums = write_steps.get(entry.get("name"))
                if nums:
                    entry["steps"] = nums
            # Tell each cross-unit call which step performs it, so Expected
            # Results can name it the way returns name theirs.
            for call in spec["expected"].get("crossUnitCalls") or []:
                label = call.get("text", "")
                nums = [s["number"] for s in steps if label and label in s.get("text", "")]
                if nums:
                    call["steps"] = nums
            filled += 1
    return filled
