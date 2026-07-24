"""Side-by-side viewer: function body | control-flow flowchart | SWE.4 test spec.

Parses the real Sample-Core source with libclang (same approach as spike.py),
builds a structured Mermaid flowchart per function, renders it to inline SVG via
mmdc, pulls the generated SWE.4 test spec from output/Sample-Core/test_specs.json,
and writes a self-contained HTML page laying the three views side by side so the
test cases can be eyeballed against the actual control flow.

Run:  python tools/swe4-derivation-spike/sidebyside.py
Out:  output/Sample-Core/sidebyside.html
"""
import os
import re
import json
import html
import subprocess
import tempfile

import clang.cindex as ci

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ci.Config.set_library_file(r"C:\Program Files\LLVM\bin\libclang.dll")

SRC = os.path.join(ROOT, "SampleCppProject", "Layer1", "Sample", "Core", "Core.cpp")
CORE_DIR = os.path.dirname(SRC)
SAMPLE_DIR = os.path.dirname(CORE_DIR)
SPECS = os.path.join(ROOT, "output", "Sample-Core", "test_specs.json")
OUT_MD = os.path.join(ROOT, "output", "Sample-Core", "sidebyside.md")

ARGS = ["-x", "c++", "-std=c++17", "-DPUBLIC=", "-DPRIVATE=", "-DPROTECTED=", "-D__OVLYINIT=",
        "-I", CORE_DIR, "-I", SAMPLE_DIR,
        "-I", os.path.join(SAMPLE_DIR, "Lib"), "-I", os.path.join(SAMPLE_DIR, "Util")]

_src_lines = open(SRC, "r", encoding="utf-8", errors="replace").read().splitlines(keepends=True)


def src_text(cur):
    e = cur.extent
    if not e.start.file:
        return ""
    s, en = e.start, e.end
    if s.line == en.line:
        return _src_lines[s.line - 1][s.column - 1:en.column - 1]
    out = [_src_lines[s.line - 1][s.column - 1:]]
    for ln in range(s.line, en.line - 1):
        out.append(_src_lines[ln])
    out.append(_src_lines[en.line - 1][:en.column - 1])
    return "".join(out).strip()


def body_source(fn):
    e = fn.extent
    return "".join(_src_lines[e.start.line - 1:e.end.line]).rstrip()


# ---------------------------------------------------------------------------
# Structured CFG -> Mermaid. build(cursor) returns (entry_id, exits) where
# exits is a list of (node_id, edge_label) still needing an onward connection.
# ---------------------------------------------------------------------------
class Flow:
    def __init__(self):
        self.n = 0
        self.lines = []

    def _nid(self):
        self.n += 1
        return f"N{self.n}"

    def _lab(self, text):
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 46:
            text = text[:44] + "…"
        return html.escape(text, quote=True).replace('"', "&quot;")

    def node(self, text, shape="rect"):
        i = self._nid()
        lab = self._lab(text)
        if shape == "diamond":
            self.lines.append(f'{i}{{"{lab}"}}')
        elif shape == "round":
            self.lines.append(f'{i}(["{lab}"])')
        else:
            self.lines.append(f'{i}["{lab}"]')
        return i

    def link(self, exits, target):
        for nid, label in exits:
            if label:
                self.lines.append(f'{nid} -->|{label}| {target}')
            else:
                self.lines.append(f'{nid} --> {target}')


SIMPLE = {ci.CursorKind.DECL_STMT, ci.CursorKind.CALL_EXPR, ci.CursorKind.BINARY_OPERATOR,
          ci.CursorKind.UNARY_OPERATOR, ci.CursorKind.CXX_UNARY_EXPR}


def _kids(c):
    return list(c.get_children())


def build_seq(f, stmts, loop_exit=None):
    """Build a sequence of statements; returns (entry, exits)."""
    entry = None
    exits = []  # dangling (node,label)
    pending_simple = []

    def flush():
        nonlocal entry, exits, pending_simple
        if not pending_simple:
            return
        txt = "<br/>".join(_kids_text(s) for s in pending_simple)
        nid = f.node(txt)
        _connect(nid)
        exits[:] = [(nid, None)]
        pending_simple = []

    def _connect(new_entry):
        nonlocal entry
        if entry is None:
            entry = new_entry
        else:
            f.link(exits, new_entry)

    for s in stmts:
        k = s.kind
        if k in (ci.CursorKind.IF_STMT, ci.CursorKind.WHILE_STMT, ci.CursorKind.FOR_STMT,
                 ci.CursorKind.DO_STMT, ci.CursorKind.SWITCH_STMT, ci.CursorKind.RETURN_STMT,
                 ci.CursorKind.BREAK_STMT, ci.CursorKind.CONTINUE_STMT):
            flush()
            e2, x2 = build_stmt(f, s, loop_exit)
            _connect(e2)
            exits[:] = x2
        else:
            pending_simple.append(s)
    flush()
    if entry is None:  # empty block
        nid = f.node("(empty)")
        return nid, [(nid, None)]
    return entry, exits


def _kids_text(s):
    t = src_text(s)
    return html.escape(re.sub(r"\s+", " ", t).strip()[:60])


def build_stmt(f, s, loop_exit=None):
    k = s.kind
    if k == ci.CursorKind.COMPOUND_STMT:
        return build_seq(f, _kids(s), loop_exit)

    if k == ci.CursorKind.RETURN_STMT:
        nid = f.node("return " + (src_text(_kids(s)[0]) if _kids(s) else ""), "round")
        return nid, []  # terminal

    if k in (ci.CursorKind.BREAK_STMT, ci.CursorKind.CONTINUE_STMT):
        nid = f.node("break" if k == ci.CursorKind.BREAK_STMT else "continue")
        return nid, []  # terminates this path (exits/repeats the loop)

    if k == ci.CursorKind.IF_STMT:
        ch = _kids(s)
        cond = src_text(ch[0])
        d = f.node("if " + cond, "diamond")
        then_e, then_x = build_stmt(f, ch[1], loop_exit)
        f.lines.append(f'{d} -->|yes| {then_e}')
        exits = list(then_x)
        if len(ch) >= 3:
            else_e, else_x = build_stmt(f, ch[2], loop_exit)
            f.lines.append(f'{d} -->|no| {else_e}')
            exits += else_x
        else:
            exits.append((d, "no"))
        return d, exits

    if k in (ci.CursorKind.WHILE_STMT, ci.CursorKind.FOR_STMT):
        ch = _kids(s)
        cond = next((c for c in ch if c.kind == ci.CursorKind.BINARY_OPERATOR), None)
        cond_txt = src_text(cond) if cond is not None else "loop"
        d = f.node(("while " if k == ci.CursorKind.WHILE_STMT else "for ") + cond_txt, "diamond")
        body = next((c for c in ch if c.kind == ci.CursorKind.COMPOUND_STMT), None)
        if body is not None:
            be, bx = build_stmt(f, body, loop_exit=d)  # break would target after-loop; approximate to d's no
            f.lines.append(f'{d} -->|yes| {be}')
            f.link(bx, d)  # loop back
        return d, [(d, "no")]

    if k == ci.CursorKind.DO_STMT:
        ch = _kids(s)
        body = next((c for c in ch if c.kind == ci.CursorKind.COMPOUND_STMT), None)
        cond = src_text(ch[-1]) if ch else "cond"
        be, bx = build_stmt(f, body, loop_exit) if body is not None else (f.node("(body)"), [])
        d = f.node("while " + cond, "diamond")
        f.link(bx, d)
        f.lines.append(f'{d} -->|yes| {be}')  # loop back
        return be, [(d, "no")]

    if k == ci.CursorKind.SWITCH_STMT:
        ch = _kids(s)
        var = src_text(ch[0]) if ch else "?"
        d = f.node("switch " + var, "diamond")
        exits = []
        body = next((c for c in ch if c.kind == ci.CursorKind.COMPOUND_STMT), None)
        if body is not None:
            for c in _kids(body):
                if c.kind in (ci.CursorKind.CASE_STMT, ci.CursorKind.DEFAULT_STMT):
                    lab = "default" if c.kind == ci.CursorKind.DEFAULT_STMT else src_text(_kids(c)[0])
                    inner = _kids(c)[-1] if _kids(c) else None
                    txt = src_text(inner) if inner is not None else ""
                    nid = f.node(txt or lab)
                    f.lines.append(f'{d} -->|{html.escape(str(lab))}| {nid}')
                    exits.append((nid, None))
        return d, exits or [(d, None)]

    # generic simple statement
    nid = f.node(_kids_text(s))
    return nid, [(nid, None)]


def flowchart(fn):
    f = Flow()
    f.lines.append("flowchart TD")
    start = f.node(fn.spelling + "()", "round")
    body = next((c for c in fn.get_children() if c.kind == ci.CursorKind.COMPOUND_STMT), None)
    if body is None:
        return None
    e, x = build_stmt(f, body)
    f.lines.append(f'{start} --> {e}')
    if x:  # only add an End when some path falls through (not all paths return)
        end = f.node("End", "round")
        f.link(x, end)
    style = ("classDef d fill:#fde68a,stroke:#b45309,color:#000;"
             "classDef t fill:#bbf7d0,stroke:#15803d,color:#000;")
    return "\n".join(f.lines)


# ---------------------------------------------------------------------------
# Branch / path analysis (spike.py logic) — enumerate the flows to cover.
# ---------------------------------------------------------------------------
CMP = re.compile(r"^\s*([A-Za-z_]\w*)\s*(<=|>=|==|!=|<|>)\s*(-?\d+)\s*$")
CMP_REV = re.compile(r"^\s*(-?\d+)\s*(<=|>=|==|!=|<|>)\s*([A-Za-z_]\w*)\s*$")


def _tokens(c):
    return set(re.findall(r"[A-Za-z_]\w*", c))


def derive(cond, params, is_loop=False):
    c = cond.strip()
    if "&&" in c or "||" in c:
        return "compound — decompose per clause"
    m = CMP.match(c) or CMP_REV.match(c)
    if m:
        g = m.groups()
        var = g[0] if CMP.match(c) else g[2]
        if var in params:
            return f"deterministic — boundary values of `{var}`"
    if _tokens(c) & set(params):
        return "coverable via a parameter value"
    if is_loop:
        return "loop-internal (iteration count)"
    if "(" in c:
        return "call/state condition — needs mock/global setup"
    return "condition on local/global — needs state setup"


def branch_list(fn, params):
    out = []

    def walk(node):
        k = node.kind
        ch = list(node.get_children())
        if k == ci.CursorKind.IF_STMT and ch:
            out.append(("if", src_text(ch[0]), False))
        elif k == ci.CursorKind.WHILE_STMT and ch:
            out.append(("while", src_text(ch[0]), True))
        elif k == ci.CursorKind.FOR_STMT:
            b = next((c for c in ch if c.kind == ci.CursorKind.BINARY_OPERATOR), None)
            if b is not None:
                out.append(("for", src_text(b), True))
        elif k == ci.CursorKind.DO_STMT and ch:
            out.append(("do-while", src_text(ch[-1]), True))
        elif k == ci.CursorKind.SWITCH_STMT and ch:
            cases = []

            def fc(n):
                for c in n.get_children():
                    if c.kind == ci.CursorKind.CASE_STMT:
                        lab = list(c.get_children())
                        cases.append(src_text(lab[0]) if lab else "?")
                    elif c.kind == ci.CursorKind.DEFAULT_STMT:
                        cases.append("default")
                    fc(c)
            fc(node)
            out.append(("switch", f"{src_text(ch[0])} in {{{', '.join(cases)}}}", False))
        for c in ch:
            walk(c)

    body = next((c for c in fn.get_children() if c.kind == ci.CursorKind.COMPOUND_STMT), None)
    if body is not None:
        walk(body)
    return out


def md_spec(spec):
    lines = []
    pre = spec.get("precondition", {})
    mocks = ", ".join(f"`{m}`" for m in pre.get("mockFunctions") or []) or "—"
    globs = ", ".join(f"`{g['name']}` ({g['direction']}"
                      + (f", init {g['value']}" if g.get('value') else "") + ")"
                      for g in pre.get("globals") or []) or "—"
    lines.append(f"**Precondition** — mocks: {mocks} · globals: {globs}")
    lines.append("")
    inputs = spec["input"].get("sets") or []
    expected = spec["expected"].get("sets") or []
    if inputs:
        lines.append("| # | Input | Expected |")
        lines.append("|---|-------|----------|")
        for i in range(max(len(inputs), len(expected))):
            inp = inputs[i] if i < len(inputs) else ""
            exp = expected[i] if i < len(expected) else ""
            lines.append(f"| {i+1} | {inp} | {exp} |")
    else:
        lines.append("_no input sets (VOID or not generated)_")
    lines.append("")
    steps = spec.get("testSteps") or []
    if steps:
        lines.append("**Test Steps:**")
        for i, s in enumerate(steps, 1):
            lines.append(f"{i}. {s}")
    return "\n".join(lines)


def main():
    specs_doc = json.load(open(SPECS, encoding="utf-8"))
    specs_by_name = {}
    for k, v in specs_doc.items():
        if k == "unitNames":
            continue
        for s in v.get("functions", []):
            specs_by_name[s["name"]] = s

    tu = ci.Index.create().parse(SRC, args=ARGS)
    out = ["# SWE.4 flow-coverage review — Sample-Core",
           "",
           "For each public function: the **body**, its **control-flow flowchart**, the **branches/flows "
           "to cover**, and the **generated SWE.4 test cases** — so we can check every flow has a case and "
           "sharpen the requirements.",
           ""]
    n = 0
    for fn in tu.cursor.walk_preorder():
        if fn.kind != ci.CursorKind.FUNCTION_DECL or not fn.is_definition():
            continue
        if fn.location.file is None or fn.location.file.name != SRC:
            continue
        name = fn.spelling
        if name not in specs_by_name:
            continue
        n += 1
        params = [a.spelling for a in fn.get_arguments()]
        spec = specs_by_name[name]
        merm = flowchart(fn)
        branches = branch_list(fn, params)

        out.append(f"## {name}({', '.join(params)})")
        out.append("")
        out.append("<details><summary>function body</summary>\n")
        out.append("```cpp")
        out.append(body_source(fn))
        out.append("```\n</details>")
        out.append("")
        out.append("**Control flow:**")
        out.append("")
        out.append("```mermaid")
        out.append(merm or "flowchart TD\n  A[no body]")
        out.append("```")
        out.append("")
        if branches:
            out.append(f"**Flows to cover ({len(branches)} decision point(s)):**")
            for kind, cond, is_loop in branches:
                out.append(f"- `{kind}` `{cond}` → _{derive(cond, params, is_loop)}_")
        else:
            out.append("**Flows to cover:** none — linear function (single path).")
        out.append("")
        out.append(f"**Generated test spec** ({spec.get('testCaseId','')} · "
                   f"{len(spec['input'].get('sets') or [])} input set(s)):")
        out.append("")
        out.append(md_spec(spec))
        out.append("\n---\n")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("wrote", OUT_MD, "(%d functions)" % n)


if __name__ == "__main__":
    main()
