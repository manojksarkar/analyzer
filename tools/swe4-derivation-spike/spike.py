"""SWE.4 transform spike — how far does deterministic branch-covering input derivation reach?

Parses the REAL sample functions via libclang, extracts every branch condition
(if / else-if / switch / loop), and runs a prototype predicate->input derivation.
Reports per function: #branches, #deterministically coverable, what's left for heuristic/LLM.
"""
import re
import clang.cindex as ci

ci.Config.set_library_file(r"C:\Program Files\LLVM\bin\libclang.dll")

BASE = r"c:\Users\User\Desktop\analyzer\tools\mock-api\workspaces\_wizard\619d9d34ea2f8c0f\SampleCppProject\Layer1"
FILES = [BASE + r"\Flow\Flowcharts.cpp", BASE + r"\Math\Utils.cpp"]
ARGS = ["-x", "c++", "-std=c++17", "-DPUBLIC=", "-DPRIVATE=", "-DPROTECTED=",
        "-I", BASE, "-I", BASE + r"\Flow", "-I", BASE + r"\Math"]

_src_cache = {}
def src_text(cur):
    e = cur.extent
    if not e.start.file:
        return ""
    p = e.start.file.name
    if p not in _src_cache:
        _src_cache[p] = open(p, "r", encoding="utf-8", errors="replace").read().splitlines(keepends=True)
    lines = _src_cache[p]
    s, en = e.start, e.end
    if s.line == en.line:
        return lines[s.line-1][s.column-1:en.column-1]
    out = [lines[s.line-1][s.column-1:]]
    for ln in range(s.line, en.line-1):
        out.append(lines[ln])
    out.append(lines[en.line-1][:en.column-1])
    return "".join(out).strip()

# ---- prototype: derive covering input(s) for a single condition ----
CMP = re.compile(r"^\s*([A-Za-z_]\w*)\s*(<=|>=|==|!=|<|>)\s*(-?\d+)\s*$")
CMP_REV = re.compile(r"^\s*(-?\d+)\s*(<=|>=|==|!=|<|>)\s*([A-Za-z_]\w*)\s*$")
MOD = re.compile(r"^\s*([A-Za-z_]\w*)\s*%\s*(\d+)\s*(==|!=)\s*(\d+)\s*$")

def _tokens(c):
    return set(re.findall(r"[A-Za-z_]\w*", c))

def derive(cond, params, is_loop=False):
    """Return (status, note). status in {DET, PARTIAL, UNSOLVED}."""
    c = cond.strip()
    if "&&" in c or "||" in c:
        return ("PARTIAL", "compound condition — decompose per clause (tractable)")
    m = CMP.match(c) or CMP_REV.match(c)
    if m:
        g = m.groups()
        var, op, k = (g[0], g[1], int(g[2])) if CMP.match(c) else (g[2], g[1], int(g[0]))
        if var in params:
            tf = {"<": (k-1, k), "<=": (k, k+1), ">": (k+1, k), ">=": (k, k-1),
                  "==": (k, k+1), "!=": (k+1, k)}[op]
            return ("DET", f"{var}: true={tf[0]}, false={tf[1]} (boundary)")
    m = MOD.match(c)
    if m and m.group(1) in params:
        var, mod, rhs = m.group(1), int(m.group(2)), int(m.group(4))
        return ("DET", f"{var}: true={rhs}, false={(rhs+1)%mod}")
    # loop condition or body-condition that references a PARAMETER (e.g. i < n, i == stop):
    # coverable by choosing the parameter (loop taken/not-taken; break reached/not).
    ptoks = _tokens(c) & set(params)
    if ptoks:
        if is_loop:
            return ("DET", f"loop bound via param {sorted(ptoks)}: not-taken=0, taken>=1")
        return ("DET", f"coverable via param {sorted(ptoks)} (choose value to hit/miss)")
    # condition on locals only (induction var) — covered by iteration count, not a distinct input
    if is_loop:
        return ("PARTIAL", "loop-internal on local counter — covered by iteration count")
    if "(" in c and ")" in c:
        return ("UNSOLVED", "call/state condition — needs mock/global setup or LLM")
    return ("PARTIAL", "condition on local/global — covered via iteration or state setup")

# ---- walk AST: collect branch conditions per function ----
def params_of(fn):
    return [a.spelling for a in fn.get_arguments()]

def conditions(node, out):
    k = node.kind
    if k == ci.CursorKind.IF_STMT:
        ch = list(node.get_children())
        if ch:
            out.append(("if", src_text(ch[0]), False))
    elif k == ci.CursorKind.WHILE_STMT:
        ch = list(node.get_children())
        if ch:
            out.append(("while", src_text(ch[0]), True))
    elif k == ci.CursorKind.DO_STMT:
        ch = list(node.get_children())
        if ch:
            out.append(("do", src_text(ch[-1]), True))   # do{...}while(COND): cond is last child
    elif k == ci.CursorKind.FOR_STMT:
        for c in node.get_children():
            if c.kind == ci.CursorKind.BINARY_OPERATOR and any(op in src_text(c) for op in ("<", ">", "==", "!=", "<=", ">=")):
                out.append(("for", src_text(c), True)); break
    elif k == ci.CursorKind.SWITCH_STMT:
        ch = list(node.get_children())
        swvar = src_text(ch[0]) if ch else "?"
        cases = []
        def find_cases(n):
            for c in n.get_children():
                if c.kind == ci.CursorKind.CASE_STMT:
                    lab = list(c.get_children())
                    cases.append(src_text(lab[0]) if lab else "?")
                elif c.kind == ci.CursorKind.DEFAULT_STMT:
                    cases.append("default")
                find_cases(c)
        find_cases(node)
        out.append(("switch", f"{swvar} in {{{', '.join(cases)}}}", False))
    for c in node.get_children():
        conditions(c, out)

def main():
    print("="*90)
    for path in FILES:
        idx = ci.Index.create()
        tu = idx.parse(path, args=ARGS)
        for fn in tu.cursor.walk_preorder():
            if fn.kind != ci.CursorKind.FUNCTION_DECL or not fn.is_definition():
                continue
            if fn.location.file is None or fn.location.file.name != path:
                continue
            params = params_of(fn)
            conds = []
            body = next((c for c in fn.get_children() if c.kind == ci.CursorKind.COMPOUND_STMT), None)
            if body is not None:
                conditions(body, conds)
            if not conds and not fn.get_children():
                continue
            calls = [c.spelling for c in fn.walk_preorder() if c.kind == ci.CursorKind.CALL_EXPR and c.spelling]
            print(f"\n### {fn.spelling}({', '.join(params)})   callees={calls or '-'}")
            if not conds:
                print("   (no branches — linear; coverage trivial; expected = f(inputs" +
                      ("/mock-returns)" if calls else ")"))
                continue
            det = part = 0
            for kind, cond, is_loop in conds:
                if kind == "switch":
                    print(f"   [switch] {cond}  -> DET: one input per case + default")
                    det += 1
                    continue
                status, note = derive(cond, params, is_loop)
                if status == "DET":
                    det += 1
                elif status == "PARTIAL":
                    part += 1
                print(f"   [{kind}] {cond!r:34} -> {status}: {note}")
            print(f"   >>> DET {det}/{len(conds)}  PARTIAL {part}  UNSOLVED {len(conds)-det-part}")
    print("\n" + "="*90)

main()
