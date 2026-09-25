"""Path solving for the UT export: pick values that drive a function down one path.

A SWE.4 spec covers every exit of a function in one row; the UT export splits it
back into one case per return (REQ-UE-04). A case is only runnable once its inputs
hold VALUES that reach its return, and its expectations say what that path yields.
This module finds them, for the conditions simple enough to solve exactly.

How: walk the flowchart CFG from the entry to the case's RETURN node. Every
DECISION / LOOP_HEAD / SWITCH_HEAD on the way contributes its condition, taken on
the edge the path follows. Each condition is parsed (a C expression subset),
rewritten over the variables a tester controls -- parameters, globals read,
mocked-callee returns, fields a mock writes back, fields of a struct parameter --
and turned into atoms: `v OP constant`, `v1 OP v2 + c`, and bit tests `v & MASK`.
Simple assignments on the path are tracked (`int s = FilRead(i, &e);`,
`count = 0;`, `gErrCount++;`), so a condition on a local that holds a mock's
result still lands on the mock.

Not solved, and said so rather than guessed: calls to functions that run for real
(their result is not ours to choose), array indexing, pointer arithmetic,
conditions on locals the path never assigned, `!=` against a symbol whose value is
unknown, a non-null pointer (it needs a real object), non-linear arithmetic in a
condition. Each leaves a note; the case keeps whatever WAS solved.

Two separate verdicts per case:
  inputs    "solved" when every condition on the path was turned into atoms and
            every constrained input got a concrete value, else "partial";
  expected  "known" when the return value (if any) was computed, else "open".
`status` = "solved" when both hold, "partial" otherwise, "unsolved" with no path.

Deterministic by construction: CFG edges are walked in file order, the value picked
for a variable is the admissible one closest to its default, nothing is random.

No file I/O here -- `ut_export.py` feeds the inputs and writes the results.
"""
import re

from utils import get_range

from .test_steps import _call_args

# Hard caps. A firmware function with dense branching can have thousands of simple
# paths; the first feasible one per return is all a case needs.
MAX_PATHS = 200
MAX_ALTERNATIVES = 64
MAX_DEPTH = 24

# Default for a variable no condition constrains. 0 reads naturally for inputs; a
# mocked callee returns 1 so that a function which passes that value straight back
# is asserted against something other than the ubiquitous 0.
DEFAULT_VALUE = 0
DEFAULT_MOCK_RETURN = 1

NONNULL = "<non-null>"   # marker: the variable must be a valid pointer / object


class Unsupported(Exception):
    """A shape this solver does not handle. The message is the reason."""


class _Infeasible(Exception):
    """The atoms of one alternative contradict each other."""


# ---------------------------------------------------------------------------
# Tokenizer + parser: a C expression subset
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"""\s*(?:
    (?P<num>0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*)
  | (?P<char>'(?:\\.|[^'\\])')
  | (?P<str>"(?:\\.|[^"\\])*")
  | (?P<op>->|<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|[-+*/%<>!()~&|^.,\[\]?:])
  | (?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)
)""", re.X)

_NEGATE = {"==": "!=", "!=": "==", "<": ">=", "<=": ">", ">": "<=", ">=": "<"}
_FLIP = {"==": "==", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<="}
_TYPE_WORDS = {"const", "volatile", "unsigned", "signed", "int", "char", "short", "long",
               "float", "double", "bool", "void", "struct", "enum", "auto", "static"}


def _tokens(text):
    out, pos, text = [], 0, text or ""
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                break
            raise Unsupported(f"cannot read `{text[pos:pos + 12].strip()}`")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


def _int_literal(text):
    t = text.rstrip("uUlL")
    return int(t, 16) if t.lower().startswith("0x") else int(t)


class _Parser:
    """Recursive descent with C precedence: `?:`, `||`, `&&`, `|`, `^`, `&`,
    equality, relational, shifts, `+ -`, `* / %`, unary `- ! ~`, casts, names,
    `a.b` / `a->b` member paths and calls. `[ ]`, `sizeof`, address-of and
    dereference raise Unsupported."""

    def __init__(self, text):
        self.toks = _tokens(text)
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if val is not None and tok[1] != val:
            raise Unsupported(f"expected `{val}`")
        self.i += 1
        return tok

    def parse(self):
        node = self.ternary()
        if self.peek()[0] is not None:
            raise Unsupported(f"unsupported operator `{self.peek()[1]}`")
        return node

    def ternary(self):
        cond = self.orx()
        if self.peek()[1] == "?":
            self.take()
            a = self.ternary()
            self.take(":")
            return ("cond", cond, a, self.ternary())
        return cond

    def _left(self, sub, ops, tag):
        node = sub()
        while self.peek()[1] in ops:
            op = self.take()[1]
            rhs = sub()
            node = (tag, node, rhs) if tag in ("or", "and") else (tag, op, node, rhs)
        return node

    def orx(self):
        return self._left(self.andx, ("||",), "or")

    def andx(self):
        return self._left(self.bitor, ("&&",), "and")

    def bitor(self):
        return self._left(self.bitxor, ("|",), "bin")

    def bitxor(self):
        return self._left(self.bitand, ("^",), "bin")

    def bitand(self):
        return self._left(self.eq, ("&",), "bin")

    def eq(self):
        return self._left(self.rel, ("==", "!="), "cmp")

    def rel(self):
        return self._left(self.shift, ("<", "<=", ">", ">="), "cmp")

    def shift(self):
        return self._left(self.add, ("<<", ">>"), "bin")

    def add(self):
        return self._left(self.mul, ("+", "-"), "bin")

    def mul(self):
        return self._left(self.unary, ("*", "/", "%"), "bin")

    def unary(self):
        val = self.peek()[1]
        if val == "-":
            self.take()
            return ("neg", self.unary())
        if val == "+":
            self.take()
            return self.unary()
        if val == "!":
            self.take()
            return ("not", self.unary())
        if val == "~":
            self.take()
            return ("bnot", self.unary())
        if val in ("&", "*", "++", "--"):
            raise Unsupported(f"operator `{val}`")
        return self.primary()

    def primary(self):
        kind, val = self.take()
        if kind is None:
            raise Unsupported("expression ends early")
        if kind == "num":
            return ("num", _int_literal(val))
        if kind == "char":
            body = val[1:-1]
            return ("num", ord(body) if len(body) == 1 else 0)
        if kind == "str":
            raise Unsupported("string literal")
        if val == "(":
            if self._looks_like_cast():
                while self.take()[1] != ")":
                    pass                 # skip `(type)`: the value is the operand's
                return self.unary()
            node = self.ternary()
            self.take(")")
            return node
        if kind == "name":
            if val == "sizeof":
                raise Unsupported("sizeof")
            if val in ("static_cast", "reinterpret_cast", "const_cast", "dynamic_cast") \
                    and self.peek()[1] == "<":
                depth = 0
                while True:                       # skip `<type>`, nested `<>` included
                    tok = self.take()[1]
                    if tok is None:
                        raise Unsupported("unfinished cast")
                    depth += (tok == "<") - (tok == ">") + 2 * (tok == "<<") - 2 * (tok == ">>")
                    if depth <= 0:
                        break
                self.take("(")
                node = self.ternary()
                self.take(")")
                return node
            path = val
            while self.peek()[1] in (".", "->"):
                self.take()
                k2, v2 = self.take()
                if k2 != "name":
                    raise Unsupported("member access")
                path = f"{path}.{v2}"
            if self.peek()[1] == "(":
                return ("call", path, self._call_args())   # `obj.m()` keeps its path
            if self.peek()[1] == "[":
                raise Unsupported("array index")
            return ("member", path) if "." in path else ("name", path)
        raise Unsupported(f"unexpected `{val}`")

    def _looks_like_cast(self):
        """True at `(` (already taken) when a type in parentheses follows, then an
        operand: `(uint8_t)x`, `(const Foo *)p`, `(int)(a + b)`. A lone name that
        is not type-like -- `(a) - b` -- stays a grouping."""
        words, j = [], 0
        while True:
            kind, val = self.peek(j)
            if kind == "name" or val == "*":
                words.append(val)
                j += 1
                continue
            break
        if not words or self.peek(j)[1] != ")":
            return False
        typelike = ("*" in words or len(words) > 1
                    or any(w in _TYPE_WORDS or w.endswith("_t") for w in words))
        nxt = self.peek(j + 1)
        return typelike and (nxt[0] in ("name", "num", "char") or nxt[1] in ("(", "-", "~", "!"))

    def _call_args(self):
        self.take("(")
        depth, start, j = 1, self.i, self.i
        while j < len(self.toks) and depth:
            v = self.toks[j][1]
            depth += (v == "(") - (v == ")")
            j += 1
        self.i = j
        return " ".join(t[1] for t in self.toks[start:j - 1])


def parse(text):
    """AST of a C condition / expression, or raise Unsupported."""
    return _Parser(text).parse()


# ---------------------------------------------------------------------------
# Context: what a name means inside one spec
# ---------------------------------------------------------------------------

_RANGE = re.compile(r"^\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*-\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*$")


def _num(text):
    t = text.strip()
    neg = t.startswith("-")
    t = t[1:] if neg else t
    v = int(t, 16) if t.lower().startswith("0x") else int(t)
    return -v if neg else v


def is_pointer(type_str):
    return "*" in (type_str or "") and "(" not in (type_str or "")


def bare_type(type_str):
    t = type_str or ""
    for tok in ("const", "volatile", "struct", "*", "&"):
        t = t.replace(tok, " ")
    return " ".join(t.split())


class Context:
    """Everything the solver needs to know about one spec.

    `variables`: key -> {"kind", "name", "type"}. Keys: `a` (parameter or global),
    `libAdd()` (mocked callee's return), `e.lba` (field a mock writes back),
    `cfg.x` (field of a struct parameter, reached by `.` or `->`).
    `constants`: symbol -> int (enumerators, numeric macros).
    `enums`: bare enum type -> [(name, value)].
    """

    def __init__(self, spec, dd=None, constants=None, layer=None):
        self.dd = dd or {}
        self.constants = dict(constants or {})
        self.enums = {}
        defines = {}
        for key, entry in self.dd.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") == "enum":
                vals = [(e.get("name"), e.get("value")) for e in entry.get("enumerators") or []
                        if isinstance(e.get("value"), int)]
                self.enums[entry.get("name") or key] = vals
                for n, v in vals:
                    self.constants.setdefault(n, v)
            elif entry.get("kind") == "define" and entry.get("name"):
                defines.setdefault(entry["name"], []).append(
                    (entry.get("layer"), entry.get("value")))
        # `#define`s in the source: the layer's own definition wins; a name with
        # two different values and no layer to choose between them is left out
        # (a wrong constant would steer the path silently).
        texts = []
        for name, entries in sorted(defines.items()):
            if name in self.constants:
                continue
            mine = [v for lay, v in entries if layer is not None and lay == layer]
            pool = mine or [v for _, v in entries]
            uniq = sorted({str(v).strip() for v in pool if v not in (None, "")})
            if len(uniq) == 1:
                texts.append(f"{name}={uniq[0]}")
        for k, v in constants_from_macros(texts, base=self.constants).items():
            self.constants.setdefault(k, v)
        self.variables = {}
        self.mock_names = []
        self.mock_params = {}
        pre = spec.get("precondition") or {}
        for m in pre.get("mocks") or []:
            nm = m.get("name", "")
            if nm:
                self.mock_names.append(nm)
                self.mock_params[nm] = m.get("parameters") or []
        self.param_types = {p.get("name", ""): p.get("type", "") for p in pre.get("parameters") or []}
        for e in (spec.get("input") or {}).get("entries") or []:
            kind, name, typ = e.get("kind"), e.get("name", ""), e.get("type", "")
            if kind == "parameter":
                self.variables[name] = {"kind": "param", "name": name,
                                        "type": typ or self.param_types.get(name, "")}
            elif kind == "global":
                self.variables[name] = {"kind": "global", "name": name, "type": typ}
            elif kind == "mockReturn":
                self.variables[name] = {"kind": "mock", "name": name, "type": typ}
            elif kind == "mockWriteback":
                self.variables[name] = {"kind": "field", "name": name, "type": typ}
        # A mock that returns nothing still gets a key, so a call to it in a
        # condition is rejected with a clear reason rather than taken for a
        # function that runs for real.
        for nm in self.mock_names:
            self.variables.setdefault(f"{nm}()", {"kind": "mock", "name": f"{nm}()", "type": ""})
        # Out-parameters are outputs to the document, but they are still passed
        # to the call -- and `if (!out) return -1;` is a condition on one.
        for name, typ in self.param_types.items():
            if name and name not in self.variables:
                self.variables[name] = {"kind": "param", "name": name, "type": typ, "out": True}
        self.out_params = [o.get("name", "") for o in
                           (spec.get("expected") or {}).get("outParameters") or []]
        self.return_type = spec.get("returnType", "")
        # {short name: {"cfg", "params"}} of functions that run for real and can be
        # executed to learn their result -- see `helpers_from_cfgs` / `execute`.
        self.helpers = {}

    def struct_field(self, path):
        """`cfg.x` for a struct / pointer-to-struct parameter `cfg`, else None."""
        base, _, field = path.partition(".")
        if "." in field or base not in self.variables:
            return None
        info = self.variables[base]
        if info["kind"] != "param":
            return None
        entry = self.dd.get(bare_type(info["type"]))
        if not isinstance(entry, dict):
            return None
        for f in entry.get("fields") or []:
            if f.get("name") == field:
                key = f"{base}.{field}"
                self.variables.setdefault(key, {"kind": "pfield", "name": key,
                                                "type": f.get("type", ""), "param": base,
                                                "field": field})
                return key
        return None

    def domain(self, key):
        """(kind, lo, hi, enumerators) for a variable: kind is int | bool | ptr."""
        typ = (self.variables.get(key) or {}).get("type", "")
        if is_pointer(typ):
            return ("ptr", None, None, None)
        bare = bare_type(typ)
        if bare == "bool":
            return ("bool", 0, 1, None)
        if bare in self.enums and self.enums[bare]:
            vals = self.enums[bare]
            return ("int", min(v for _, v in vals), max(v for _, v in vals), vals)
        rng = get_range(typ, self.dd) if typ else "NA"
        m = _RANGE.match(rng or "")
        if m:
            return ("int", _num(m.group(1)), _num(m.group(2)), None)
        return ("int", -0x80000000, 0x7FFFFFFF, None)


# ---------------------------------------------------------------------------
# Symbolic evaluation along a path
# ---------------------------------------------------------------------------

class _Env:
    """Aliases in force at a point of the path: local / reassigned name -> AST.
    Stored ASTs are frozen (see `_freeze`), so resolution never loops.

    `visible`: the kinds of context variable a name may resolve to. None = all
    (the function under test); a helper being executed sees only globals and
    stubs, never the caller's parameters."""

    def __init__(self, ctx, visible=None):
        self.ctx = ctx
        self.alias = {}
        self.visible = visible

    def copy(self):
        e = _Env(self.ctx, self.visible)
        e.alias = dict(self.alias)
        return e

    def sees(self, key):
        info = self.ctx.variables.get(key)
        return info is not None and (self.visible is None or info["kind"] in self.visible)

    def term(self, node, depth=0):
        """Rewrite `node` over the context's variables and constants."""
        if depth > MAX_DEPTH:
            raise Unsupported("expression too deep")
        tag = node[0]
        if tag in ("num", "var", "const", "sym", "null"):
            return node
        if tag == "opaque":
            raise Unsupported(f"`{_short(node[1])}` is not a simple expression")
        if tag == "name":
            n = node[1]
            if n in self.alias:
                return self.term(self.alias[n], depth + 1)
            if self.sees(n):
                return ("var", n)
            if n in ("true", "TRUE"):
                return ("num", 1)
            if n in ("false", "FALSE"):
                return ("num", 0)
            if n in ("NULL", "nullptr"):
                return ("null",)
            short = n.split("::")[-1]
            if n in self.ctx.constants or short in self.ctx.constants:
                return ("const", n, self.ctx.constants.get(n, self.ctx.constants.get(short)))
            if n.isupper() or "::" in n:
                return ("sym", n)            # a macro / enumerator we have no value for
            raise Unsupported(f"`{n}` is a local the path never assigns")
        if tag == "member":
            path = node[1]
            if path in self.alias:
                return self.term(self.alias[path], depth + 1)
            if self.sees(path):
                return ("var", path)
            key = self.ctx.struct_field(path) if self.sees(path.partition(".")[0]) else None
            if key:
                return ("var", key)
            raise Unsupported(f"`{path}` is not an input")
        if tag == "call":
            name = node[1].replace("::", ".").split(".")[-1]
            if name in self.ctx.mock_names:
                key = f"{name}()"
                if not (self.ctx.variables.get(key) or {}).get("type"):
                    raise Unsupported(f"`{name}()` returns nothing to test")
                return ("var", key)
            if "." in node[1]:
                raise Unsupported(f"method call `{node[1]}()` on an object that runs for real")
            raise Unsupported(f"`{node[1]}()` runs for real -- its result is not an input")
        if tag == "neg":
            inner = self.term(node[1], depth + 1)
            if inner[0] in ("num", "const"):
                return ("num", -value_of(inner))
            return ("bin", "-", ("num", 0), inner)
        if tag == "bnot":
            inner = self.term(node[1], depth + 1)
            if inner[0] in ("num", "const"):
                return ("num", ~value_of(inner))
            raise Unsupported("`~` of an input")
        if tag == "bin":
            left, right = self.term(node[2], depth + 1), self.term(node[3], depth + 1)
            if left[0] in ("num", "const") and right[0] in ("num", "const"):
                return ("num", _fold(node[1], value_of(left), value_of(right)))
            return ("bin", node[1], left, right)
        if tag in ("cmp", "and", "or", "not", "cond"):
            return node
        raise Unsupported(f"expression `{tag}`")


def value_of(t):
    return t[1] if t[0] == "num" else t[2]


def _fold(op, a, b):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op in ("/", "%"):
        if b == 0:
            raise Unsupported("division by zero")
        q = abs(a) // abs(b) * (1 if (a >= 0) == (b >= 0) else -1)   # C truncation
        return q if op == "/" else a - q * b
    if op == "&":
        return a & b
    if op == "|":
        return a | b
    if op == "^":
        return a ^ b
    if op == "<<":
        return a << b
    if op == ">>":
        return a >> b
    raise Unsupported(f"operator `{op}`")


def _freeze(node, env):
    """`node` with every aliased name replaced by the AST it holds NOW. Stored
    before `x = x + 1` takes effect, so the old `x` is captured, not a cycle."""
    tag = node[0]
    if tag in ("name", "member"):
        if node[1] in env.alias:
            return env.alias[node[1]]
        # Not reassigned yet: its value now is the original -- an input, a
        # constant, or a local nobody set. Resolve it here, so `x = x / 2`
        # stores `x_original / 2` instead of a reference back to itself.
        try:
            return env.term(node)
        except Unsupported:
            return ("opaque", node[1])
    if tag in ("neg", "not", "bnot"):
        return (tag, _freeze(node[1], env))
    if tag in ("bin", "cmp"):
        return (tag, node[1], _freeze(node[2], env), _freeze(node[3], env))
    if tag in ("and", "or"):
        return (tag, _freeze(node[1], env), _freeze(node[2], env))
    if tag == "cond":
        return ("cond", _freeze(node[1], env), _freeze(node[2], env), _freeze(node[3], env))
    return node


def _linear(t):
    """(var_key, offset) for `v`, `v + c`, `v - c`, `c + v`; else None."""
    if t[0] == "var":
        return t[1], 0
    if t[0] == "bin" and t[1] in ("+", "-"):
        a, b = t[2], t[3]
        if a[0] == "var" and b[0] in ("num", "const"):
            return a[1], (value_of(b) if t[1] == "+" else -value_of(b))
        if t[1] == "+" and b[0] == "var" and a[0] in ("num", "const"):
            return b[1], value_of(a)
    return None


def _masked(t):
    """(var_key, mask) for `v & MASK` / `MASK & v`; else None."""
    if t[0] == "bin" and t[1] == "&":
        a, b = t[2], t[3]
        if a[0] == "var" and b[0] in ("num", "const"):
            return a[1], value_of(b)
        if b[0] == "var" and a[0] in ("num", "const"):
            return b[1], value_of(a)
    return None


def _atom(op, lhs, rhs):
    """One comparison, rewritten to atoms. [] = always true, [("FALSE",)] = never.

    Atom shapes:  (key, op, const, shown)            v OP c
                  ("REL", k1, op, k2, offset)        k1 OP k2 + offset
                  ("BITS", key, mask, value, equal)  (v & mask) == / != value
    """
    if lhs[0] in ("num", "const") and rhs[0] in ("num", "const"):
        return [] if _compare(op, value_of(lhs), value_of(rhs)) else [("FALSE",)]
    if lhs[0] in ("num", "const", "null", "sym"):
        lhs, rhs, op = rhs, lhs, _FLIP[op]
    masked = _masked(lhs)
    if masked and rhs[0] in ("num", "const") and op in ("==", "!="):
        return [("BITS", masked[0], masked[1], value_of(rhs), op == "==")]
    lin = _linear(lhs)
    if lin is None:
        raise Unsupported("condition on an expression the solver cannot invert")
    key, off = lin
    if rhs[0] in ("num", "const"):
        c = value_of(rhs) - off
        shown = rhs[1] if rhs[0] == "const" and off == 0 else None
        return [(key, op, c, shown)]
    if rhs[0] == "null" and off == 0 and op in ("==", "!="):
        return [(key, op, None, None)]
    if rhs[0] == "sym" and off == 0 and op in ("==", "!="):
        return [(key, op, ("sym", rhs[1]), rhs[1])]
    rlin = _linear(rhs)
    if rlin is not None:
        if rlin[0] == key:
            ok = _compare(op, off, rlin[1])        # v + a OP v + b
            return [] if ok else [("FALSE",)]
        return [("REL", key, op, rlin[0], rlin[1] - off)]
    raise Unsupported("comparison against something other than a constant or an input")


def _compare(op, a, b):
    return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b,
            ">": a > b, ">=": a >= b}[op]


def assume(node, truth, env):
    """Alternatives (list of atom lists) under which `node` evaluates to `truth`."""
    tag = node[0]
    if tag == "not":
        return assume(node[1], not truth, env)
    if tag == "and":
        if truth:
            return _product(assume(node[1], True, env), assume(node[2], True, env))
        return _cap(assume(node[1], False, env)
                    + _product(assume(node[1], True, env), assume(node[2], False, env)))
    if tag == "or":
        if truth:
            return _cap(assume(node[1], True, env)
                        + _product(assume(node[1], False, env), assume(node[2], True, env)))
        return _product(assume(node[1], False, env), assume(node[2], False, env))
    if tag == "cmp":
        op = node[1] if truth else _NEGATE[node[1]]
        return [_atom(op, env.term(node[2]), env.term(node[3]))]
    if tag == "cond":
        raise Unsupported("`?:` inside a condition")
    # A bare value is a truth test: `if (p)`, `if (ready)`, `if (Foo())`, `if (f & M)`.
    t = env.term(node)
    if t[0] in ("cmp", "and", "or", "not", "cond"):
        return assume(t, truth, env)          # `bool ok = a > b; if (ok)`
    if t[0] in ("num", "const"):
        return [[]] if bool(value_of(t)) == truth else [[("FALSE",)]]
    if t[0] == "null":
        return [[]] if not truth else [[("FALSE",)]]
    return [_atom("!=" if truth else "==", t, ("num", 0))]


def _product(xs, ys):
    return _cap([a + b for a in xs for b in ys])


def _cap(alts):
    return alts[:MAX_ALTERNATIVES]


# ---------------------------------------------------------------------------
# Solving atoms
# ---------------------------------------------------------------------------

def _solve_var(key, atoms, ctx, notes):
    """Pick a value for one variable. Returns (value, shown) or raises _Infeasible.
    `value` is an int, None (null pointer), NONNULL, or ("sym", name)."""
    kind, lo, hi, enums = ctx.domain(key)
    info = ctx.variables.get(key) or {}
    unary = [a for a in atoms if a[0] != "BITS"]
    bits = [a for a in atoms if a[0] == "BITS"]
    if kind == "ptr":
        want_null = None
        for _, op, c, _s in unary:
            if c not in (None, 0):
                raise _Infeasible()
            is_null = op == "=="
            if want_null is not None and want_null != is_null:
                raise _Infeasible()
            want_null = is_null
        if bits:
            raise _Infeasible()
        if want_null is False:
            notes.append(f"`{key}` must be a valid pointer -- give it an object")
            return NONNULL, None
        return None, None
    eq, ne, syms_ne, shown_eq = None, set(), set(), None
    for _, op, c, shown in unary:
        if isinstance(c, tuple):                      # symbol with no known value
            if op == "==":
                if eq is not None and eq != c:
                    raise _Infeasible()
                eq, shown_eq = c, shown
            else:
                syms_ne.add(c[1])
            continue
        if c is None:                                  # `x == NULL` on a non-pointer
            c = 0
        if op == "==":
            if eq is not None and eq != c:
                raise _Infeasible()
            eq, shown_eq = c, shown
        elif op == "!=":
            ne.add(c)
        elif op == "<":
            hi = min(hi, c - 1)
        elif op == "<=":
            hi = min(hi, c)
        elif op == ">":
            lo = max(lo, c + 1)
        elif op == ">=":
            lo = max(lo, c)
    if isinstance(eq, tuple):
        if bits:
            raise _Infeasible()
        return eq, shown_eq or eq[1]
    if bits:
        base = _bit_value(bits)
        cand = eq if eq is not None else base
        if not _bits_ok(cand, bits) or not (lo <= cand <= hi) or cand in ne:
            raise _Infeasible()
        return cand, shown_eq if eq is not None else None
    if eq is not None:
        if not (lo <= eq <= hi) or eq in ne:
            raise _Infeasible()
        return eq, shown_eq
    if lo > hi:
        raise _Infeasible()
    if syms_ne:
        if enums:
            for n, v in sorted(enums, key=lambda nv: (abs(nv[1]), nv[1])):
                if lo <= v <= hi and v not in ne and n not in syms_ne:
                    return v, n
            raise _Infeasible()
        notes.append(f"`{key}` must differ from {', '.join(sorted(syms_ne))}, "
                     f"whose value is unknown")
    if enums:
        for n, v in sorted(enums, key=lambda nv: (abs(nv[1]), nv[1])):
            if lo <= v <= hi and v not in ne:
                return v, n
        raise _Infeasible()
    prefer = DEFAULT_MOCK_RETURN if info.get("kind") == "mock" and not atoms else DEFAULT_VALUE
    for cand in _candidates(prefer, lo, hi):
        if cand not in ne:
            return cand, None
    raise _Infeasible()


def _bit_value(bits):
    """Smallest value meeting every `(v & mask) ==/!= value` atom, built bit by bit."""
    must, forbid = 0, 0
    for _, _, mask, val, equal in bits:
        if equal:
            if val & ~mask:
                raise _Infeasible()
            must |= val
            forbid |= mask & ~val
    for _, _, mask, val, equal in bits:
        if not equal and val == 0:                    # some bit of mask is set
            if (must & mask) == 0:
                free = mask & ~forbid
                if not free:
                    raise _Infeasible()
                must |= free & -free                  # lowest free bit
    if must & forbid:
        raise _Infeasible()
    return must


def _bits_ok(v, bits):
    return all(((v & mask) == val) == equal for _, _, mask, val, equal in bits)


def _candidates(prefer, lo, hi):
    """Admissible values nearest to `prefer`, in order."""
    start = min(max(prefer, lo), hi)
    yield start
    for d in range(1, 64):
        for c in (start + d, start - d):
            if lo <= c <= hi:
                yield c


def _solve_atoms(atoms, ctx, notes):
    """{key: (value, shown)} satisfying every atom, or raise _Infeasible.

    Single-variable atoms are solved per variable. `REL` atoms (`a > b`) are then
    satisfied greedily: variables are fixed in first-appearance order, the right
    side before the left, and each takes the bound its already-fixed partners
    imply. No backtracking -- a chain the greedy order cannot meet is infeasible.
    """
    if any(a[0] == "FALSE" for a in atoms):
        raise _Infeasible()
    per_var, rels = {}, []
    for a in atoms:
        if a[0] == "REL":
            rels.append(a)
        elif a[0] == "BITS":
            per_var.setdefault(a[1], []).append(a)
        else:
            per_var.setdefault(a[0], []).append(a)
    order = []
    for _, k1, _, k2, _ in rels:
        for k in (k2, k1):
            if k not in order:
                order.append(k)
    out = {}
    for k in sorted(per_var):
        if k not in order:
            out[k] = _solve_var(k, per_var[k], ctx, notes)
    for k in order:
        derived = []
        for _, k1, op, k2, off in rels:
            if k1 == k and k2 in out and isinstance(out[k2][0], int):
                derived.append((k, op, out[k2][0] + off, None))
            elif k2 == k and k1 in out and isinstance(out[k1][0], int):
                derived.append((k, _FLIP[op], out[k1][0] - off, None))
        out[k] = _solve_var(k, per_var.get(k, []) + derived, ctx, notes)
    for _, k1, op, k2, off in rels:
        a, b = out[k1][0], out[k2][0]
        if not (isinstance(a, int) and isinstance(b, int) and _compare(op, a, b + off)):
            raise _Infeasible()
    return out


# ---------------------------------------------------------------------------
# Statements and paths
# ---------------------------------------------------------------------------

_CONTINUES = ("+", "-", "*", "/", "%", "&", "|", "^", "=", "<", ">", ",", "(", "?", ":", "!")
_ASSIGN = re.compile(r"^(?P<lhs>[^=!<>]*?[\w\]\)])\s*(?P<op><<=|>>=|[-+*/%&|^]?=)(?!=)\s*(?P<rhs>.+)$",
                     re.S)
_INCDEC = re.compile(r"^(?:(?P<pre>\+\+|--)\s*(?P<a>[\w.]+)|(?P<b>[\w.]+)\s*(?P<post>\+\+|--))$")


def statements(raw):
    """A node's source split into statements.

    The flowchart engine groups up to five statements per ACTION node and drops
    their semicolons, one per line. So a newline at nesting depth 0 ends a
    statement too -- unless the line visibly continues (ends on an operator, or
    the next one starts with one)."""
    out, depth, cur = [], 0, ""
    text = raw or ""
    for i, c in enumerate(text):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if depth == 0 and c == ";":
            out.append(cur)
            cur = ""
            continue
        if depth == 0 and c == "\n":
            nxt = text[i + 1:].lstrip()
            if not cur.rstrip().endswith(_CONTINUES) and not nxt.startswith(_CONTINUES):
                out.append(cur)
                cur = ""
                continue
        cur += c
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def _lhs_name(lhs):
    """`uint16_t i` -> `i`, `*out` -> None (a write through a pointer), `e.lba` -> `e.lba`."""
    text = lhs.strip()
    if text.startswith("*") or "[" in text:
        return None
    parts = text.split()
    name = parts[-1].lstrip("*&") if parts else ""
    return name if re.match(r"^[A-Za-z_][\w.]*$", name) else None


def _base(name):
    return ("member", name) if "." in name else ("name", name)


def _apply_statement(stmt, env, calls, ctx):
    """Update `env` for one statement; record mock calls made in it."""
    s = stmt.strip().rstrip(";").strip().replace("->", ".")
    if not s or s.startswith(("return", "break", "continue", "goto", "case ", "default",
                              "(void)")):
        return
    for nm in ctx.mock_names:
        if nm + "(" in s:
            calls.append((nm, _call_args(s, nm), env.copy()))
    m = _INCDEC.match(s)
    if m:
        name = m.group("a") or m.group("b")
        op = "+" if (m.group("pre") or m.group("post")) == "++" else "-"
        env.alias[name] = ("bin", op, _freeze(_base(name), env), ("num", 1))
        return
    m = _ASSIGN.match(s)
    if not m:
        return
    name = _lhs_name(m.group("lhs"))
    if not name:
        return
    try:
        rhs = _freeze(parse(m.group("rhs")), env)
    except Unsupported:
        rhs = ("opaque", m.group("rhs").strip())
    op = m.group("op")
    if op != "=":
        rhs = ("bin", op[:-1], _freeze(_base(name), env), rhs)
    env.alias[name] = rhs


def _loop_parts(raw):
    """(init statements, condition text) of a LOOP_HEAD's raw code."""
    text = (raw or "").strip()
    if text.startswith("do-while:"):
        return [], text[len("do-while:"):].strip()
    m = re.match(r"^for\s*\((.*)\)\s*$", text, re.S)
    if m:
        parts = _semi_split(m.group(1))
        init = parts[0] if parts else ""
        cond = parts[1] if len(parts) > 1 else ""
        return ([init] if init.strip() else []), (cond.strip() or "1")
    m = re.match(r"^while\s*\((.*)\)\s*$", text, re.S)
    if m:
        return [], m.group(1)
    return [], text


def _semi_split(text):
    out, depth, cur = [], 0, ""
    for c in text:
        depth += (c == "(") - (c == ")")
        if c == ";" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += c
    out.append(cur)
    return out


def _switch_subject(raw):
    m = re.match(r"^\s*switch\s*\((.*)\)\s*$", raw or "", re.S)
    return (m.group(1) if m else raw or "").strip()


def _case_value(label):
    return (label or "")[len("case "):].strip().rstrip(":").strip()


def paths_to(cfg, target, limit=MAX_PATHS):
    """Simple paths entry -> target as [(node_id, edge_label_taken)], file order."""
    nodes = {n["id"]: n for n in cfg.get("nodes", [])}
    succ = {nid: [] for nid in nodes}
    for e in cfg.get("edges", []):
        if e.get("source") in succ and e.get("target") in nodes:
            succ[e["source"]].append((e["target"], e.get("label")))
    out, stack = [], [(cfg.get("entry"), [], {cfg.get("entry")})]
    while stack and len(out) < limit:
        nid, trail, seen = stack.pop()
        if nid == target:
            out.append(trail + [(nid, None)])
            continue
        for nxt, label in reversed(succ.get(nid, [])):
            if nxt not in seen:
                stack.append((nxt, trail + [(nid, label)], seen | {nxt}))
    return out, nodes, succ


def _walk(path, nodes, succ, ctx):
    """Run one path: (alternatives, env at the return, mock calls, skipped).

    `skipped` = [(note, pending)]: a condition the solver could not turn into
    atoms. `pending` = ([(ast, truth)], env snapshot) when it at least parsed --
    it can still be CHECKED once values are chosen (a helper in it can be
    executed); None when it did not parse at all."""
    env = _Env(ctx)
    alts, skipped, calls = [[]], [], []
    for nid, label in path:
        node = nodes.get(nid) or {}
        ntype, raw = node.get("type", ""), node.get("rawCode") or ""
        if ntype == "ACTION":
            for st in statements(raw):
                _apply_statement(st, env, calls, ctx)
            continue
        if ntype == "RETURN":
            for nm in ctx.mock_names:
                if nm + "(" in raw:
                    calls.append((nm, _call_args(raw, nm), env.copy()))
            continue
        if ntype not in ("DECISION", "LOOP_HEAD", "SWITCH_HEAD") or label is None:
            continue
        try:
            if ntype == "SWITCH_HEAD":
                subject = parse(_switch_subject(raw))
                if label == "default":
                    checks = [(("cmp", "!=", subject, parse(_case_value(other))), True)
                              for _, other in succ.get(nid, [])
                              if other and other.startswith("case ")]
                elif str(label).startswith("case "):
                    checks = [(("cmp", "==", subject, parse(_case_value(label))), True)]
                else:
                    continue
            else:
                init, cond_text = _loop_parts(raw) if ntype == "LOOP_HEAD" else ([], raw)
                for st in init:
                    _apply_statement(st, env, calls, ctx)
                for nm in ctx.mock_names:
                    if nm + "(" in cond_text:
                        calls.append((nm, _call_args(cond_text, nm), env.copy()))
                checks = [(parse(cond_text), str(label).strip().lower() in ("yes", "true"))]
        except Unsupported as exc:
            skipped.append((f"condition `{_short(raw)}` ({label}) not solved: {exc}", None))
            continue
        try:
            part = [[]]
            for ast, truth in checks:
                part = _product(part, assume(ast, truth, env))
            alts = _product(alts, part)
        except Unsupported as exc:
            skipped.append((f"condition `{_short(raw)}` ({label}) not solved: {exc}",
                            (checks, env.copy())))
    return alts, env, calls, skipped


def _short(text, n=60):
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def solve(spec, cfg, ctx):
    """{step_number: result} for every return step of `spec` (one step "" when the
    spec has no return -- a void function still gets one case).

    result = {
      "status":   "solved" | "partial" | "unsolved",
      "inputs":   "solved" | "partial",
      "expected": "known" | "open",
      "values":   {variable_key: (value, shown)},  # chosen inputs
      "return":   display string | None,          # what this path returns
      "globals":  {name: display string | None},  # written globals after the path
      "stubCalls": [(mock, {param: display})],    # mocks called, known arguments
      "notes":    [str],                          # why anything is not solved
    }
    """
    steps = {s.get("number"): s for s in spec.get("testSteps") or []}
    returns = (spec.get("expected") or {}).get("returns") or []
    written = [g.get("name", "") for g in (spec.get("expected") or {}).get("globals") or []]
    node_ids = {n.get("id") for n in (cfg or {}).get("nodes", [])}
    targets = []
    if not returns:
        exits = list((cfg or {}).get("exits") or [])
        targets.append(("", exits[0] if exits else None))
    else:
        targets = [(r.get("step", ""), (steps.get(r.get("step", "")) or {}).get("nodeId"))
                   for r in returns]
    out = {}
    for number, node_id in targets:
        if not cfg or not node_id:
            out[number] = _unsolved("no control-flow graph for this return")
            continue
        if node_id not in node_ids:
            out[number] = _unsolved("this return is in a callee spliced into the interaction, "
                                    "not in the function's own graph")
            continue
        result = _solve_path_to(cfg, node_id, ctx, written)
        if result["status"] != "solved":
            executed = _solve_by_execution(cfg, node_id, ctx, written, result)
            if executed is not None:
                result = executed
        out[number] = _with_format_notes(result, ctx)
    return out


def _with_format_notes(result, ctx):
    """Notes about what the TARGET format cannot carry. Informational: they do not
    change the verdicts -- the solving itself is complete."""
    notes = list(result["notes"])
    for name in ctx.out_params:
        notes.append(f"`{name}` must point at a buffer the function writes; "
                     "the target format has no value for that")
    if notes != result["notes"]:
        result = dict(result, notes=notes)
    return result


MAX_EXEC_SEARCH = 400     # whole-function executions tried per return


def _solve_by_execution(cfg, node_id, ctx, written, symbolic):
    """The fallback when path conditions could not be solved symbolically: EXECUTE
    the function with candidate inputs and keep the first set that really exits
    through `node_id`. The run is the proof -- its return value and the globals
    it leaves become the expected values. Candidates: the symbolic attempt's
    values first, then small values and the function's own literals, one input
    at a time, then pairs. None when no candidate reaches the return."""
    nodes = {n["id"]: n for n in cfg.get("nodes", [])}
    seed = dict(symbolic.get("values") or {}) or _fill_defaults({}, ctx)
    literals = _literals(nodes)
    keys = [k for k, info in sorted(ctx.variables.items())
            if info["kind"] in ("param", "global", "mock", "field", "pfield")
            and isinstance((seed.get(k) or (None,))[0], int)]

    def cands(k):
        kind, lo, hi, enums = ctx.domain(k)
        if enums:
            return [(v, n) for n, v in enums]
        if kind == "bool":
            return [(0, None), (1, None)]
        pool = {0, 1, -1, 2, -2, 3, 5, 10, -10, 100, -100, 1000, -1000}
        pool |= {lit + d for lit in literals for d in (-1, 0, 1)}
        pool |= {-lit + d for lit in literals for d in (-1, 0, 1)}
        return [(c, None) for c in sorted(pool, key=lambda c: (abs(c), c)) if lo <= c <= hi]

    def attempt(vals):
        try:
            nid, value, env = run_function(cfg, ctx, vals)
        except (Unsupported, RecursionError, ValueError, OverflowError):
            return None
        return (vals, value, env) if nid == node_id else None

    found = attempt(seed)
    tried = 1
    for k in keys:
        if found or tried > MAX_EXEC_SEARCH:
            break
        for c in cands(k):
            tried += 1
            if tried > MAX_EXEC_SEARCH:
                break
            found = attempt(dict(seed, **{k: c}))
            if found:
                break
    if not found:
        for i, k1 in enumerate(keys):
            for k2 in keys[i + 1:]:
                for c1 in cands(k1)[:8]:
                    for c2 in cands(k2)[:8]:
                        tried += 1
                        if found or tried > MAX_EXEC_SEARCH:
                            break
                        found = attempt(dict(seed, **{k1: c1, k2: c2}))
    if not found:
        return None
    vals, value, env = found
    node = nodes.get(node_id) or {}
    has_expr = node.get("type") == "RETURN" and \
        (node.get("rawCode") or "").strip().rstrip(";").strip() not in ("return", "")
    ret = None
    if has_expr and value is not None:
        ret = ("true" if value else "false") if bare_type(ctx.return_type) == "bool" else str(value)
    globals_after = {}
    for g in written:
        disp, _ = _eval_display(env.alias.get(g, ("name", g)), env, vals, ctx)
        globals_after[g] = disp if not isinstance(disp, bool) else str(int(disp))
    stub_calls, seen = [], set()
    for name, args in env.record:
        if name in seen:
            continue
        seen.add(name)
        params = ctx.mock_params.get(name) or []
        known = {}
        for i, v in enumerate(args):
            if i < len(params) and v is not None:
                ptype = params[i].get("type", "")
                if not (is_pointer(ptype) and "const" not in ptype):
                    known[params[i].get("name") or f"arg{i}"] = str(v)
        stub_calls.append((name, known))
    return {"status": "solved", "inputs": "solved", "expected": "known", "values": vals,
            "return": ret, "globals": globals_after, "stubCalls": stub_calls,
            "notes": ["found by executing the function: the conditions could not be "
                      "solved directly"],
            "method": "execution"}


def _unsolved(note):
    return {"status": "unsolved", "inputs": "partial", "expected": "open", "values": {},
            "return": None, "globals": {}, "stubCalls": [], "notes": [note]}


MAX_SEARCH = 600          # candidate value sets tried per return


def _holds(pending, values, ctx):
    """True / False: does every check of a pending condition hold under `values`?
    None when it cannot be evaluated even concretely."""
    checks, env = pending
    try:
        return all(bool(_eval(ast, env, values, ctx)) == truth for ast, truth in checks)
    except (Unsupported, RecursionError):
        return None


def _atom_ok(a, vals):
    """A solved atom, re-checked against a candidate value set."""
    if a[0] == "FALSE":
        return False
    if a[0] == "REL":
        _, k1, op, k2, off = a
        x, y = (vals.get(k1) or (None,))[0], (vals.get(k2) or (None,))[0]
        return isinstance(x, int) and isinstance(y, int) and _compare(op, x, y + off)
    if a[0] == "BITS":
        _, k, mask, val, equal = a
        x = (vals.get(k) or (None,))[0]
        return isinstance(x, int) and ((x & mask) == val) == equal
    k, op, c, _ = a
    x = (vals.get(k) or (None,))[0]
    if isinstance(c, tuple):
        return (x == c) == (op == "==")
    if c is None:
        return (x is None or x == 0) == (op == "==")
    return isinstance(x, int) and _compare(op, x, c)


def _literals(nodes):
    """Integer literals in the function's own code: the thresholds its branches use."""
    found = set()
    for n in nodes.values():
        for m in re.findall(r"\b(0[xX][0-9a-fA-F]+|\d+)\b", n.get("rawCode") or ""):
            try:
                found.add(_int_literal(m))
            except ValueError:
                pass
    return sorted(found)[:24]


def _search(atoms, pendings, values, ctx, literals):
    """Values that satisfy the path's atoms AND its pending conditions (checked
    concretely, helpers executed), found by trying small values, the function's
    own literals and their neighbours -- one variable at a time, then pairs.
    Bounded by MAX_SEARCH; None when nothing works."""
    keys = [k for k, info in sorted(ctx.variables.items())
            if info["kind"] in ("param", "global", "mock", "field", "pfield")
            and isinstance((values.get(k) or (None,))[0], int)]

    def cands(k):
        kind, lo, hi, enums = ctx.domain(k)
        if enums:
            return [(v, n) for n, v in enums]
        if kind == "bool":
            return [(0, None), (1, None)]
        pool = {0, 1, -1, 2, -2, 3, 5, 10, -10, 100, -100, 1000, -1000}
        pool |= {lit + d for lit in literals for d in (-1, 0, 1)}
        pool |= {-lit + d for lit in literals for d in (-1, 0, 1)}
        return [(c, None) for c in sorted(pool, key=lambda c: (abs(c), c)) if lo <= c <= hi]

    def ok(vals):
        return (all(_atom_ok(a, vals) for a in atoms)
                and all(_holds(p, vals, ctx) is True for p in pendings))

    tried = 0
    for k in keys:
        for c in cands(k):
            tried += 1
            if tried > MAX_SEARCH:
                return None
            vals = dict(values)
            vals[k] = c
            if ok(vals):
                return vals
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            for c1 in cands(k1)[:8]:
                for c2 in cands(k2)[:8]:
                    tried += 1
                    if tried > MAX_SEARCH:
                        return None
                    vals = dict(values)
                    vals[k1], vals[k2] = c1, c2
                    if ok(vals):
                        return vals
    return None


def _solve_path_to(cfg, node_id, ctx, written):
    paths, nodes, succ = paths_to(cfg, node_id)
    if not paths:
        return _unsolved("no path from the entry reaches this return")
    best = None
    for path in paths:
        alts, env, calls, skipped = _walk(path, nodes, succ, ctx)
        for atoms in alts:
            notes = []
            try:
                values = _solve_atoms(atoms, ctx, notes)
            except (_Infeasible, Unsupported):
                continue
            # A condition that only parsed can still be checked later: it
            # counts less against the path than one that did not parse.
            cost = sum(2 if p is None else 1 for _, p in skipped) + 2 * len(notes)
            cand = (cost, values, env, calls, skipped, notes, atoms)
            if best is None or cand[0] < best[0]:
                best = cand
            break
        if best is not None and best[0] == 0:
            break
    if best is None:
        return _unsolved("every path to this return has conditions that contradict each other")
    _, values, env, calls, skipped, notes, atoms = best
    values = _fill_defaults(values, ctx)
    pendings = [p for _, p in skipped if p is not None]
    unsettled = [n for n, p in skipped if p is None]
    if pendings:
        if not all(_holds(p, values, ctx) is True for p in pendings):
            found = _search(atoms, pendings, values, ctx, _literals(nodes))
            if found is None:
                unsettled += [n for n, p in skipped if p is not None]
            else:
                values = found
    input_notes = unsettled + list(notes)
    expected_notes = []
    ret_display = None
    node = nodes.get(node_id) or {}
    if node.get("type") == "RETURN":
        ret_display, ret_note = _return_display(node, env, values, ctx)
        if ret_note:
            expected_notes.append(ret_note)
    globals_after = {}
    for g in written:
        disp, _ = _eval_display(env.alias.get(g, ("name", g)), env, values, ctx)
        globals_after[g] = disp
    inputs = "solved" if not input_notes else "partial"
    expected = "known" if not expected_notes else "open"
    return {"status": "solved" if inputs == "solved" and expected == "known" else "partial",
            "inputs": inputs, "expected": expected, "values": values,
            "return": ret_display, "globals": globals_after,
            "stubCalls": _stub_calls(calls, values, ctx),
            "notes": input_notes + expected_notes}


def _fill_defaults(values, ctx):
    """Every controllable variable gets a value; unconstrained ones the default."""
    out = dict(values)
    for key, info in ctx.variables.items():
        if key in out or info["kind"] == "pfield":
            continue
        if info["kind"] == "mock" and not info.get("type"):
            continue
        try:
            out[key] = _solve_var(key, [], ctx, [])
        except _Infeasible:
            continue
    return out


def display(value, shown, type_str=""):
    """A chosen value as the target format writes it: a C expression string, a JSON
    bool for a `bool` input, None for a null pointer (and for NONNULL, which has
    no literal)."""
    if shown:
        return shown
    if value is None or value == NONNULL:
        return None
    if isinstance(value, tuple):
        return value[1]
    if bare_type(type_str) == "bool":
        return bool(value)
    return str(value)


def _eval(node, env, values, ctx, depth=0, calls=0):
    """Concrete int for an expression under the chosen values, or raise Unsupported.

    Walks the raw AST, so a call can be answered on the way: a mock by the value
    chosen for its return, a helper that runs for real by EXECUTING its CFG with
    the concrete arguments (`execute`)."""
    if depth > MAX_DEPTH:
        raise Unsupported("expression too deep")
    tag = node[0]
    if tag == "num":
        return node[1]
    if tag == "const":
        return node[2]
    if tag == "null":
        return 0
    if tag == "var":
        v, _ = values.get(node[1], (None, None))
        if not isinstance(v, int):
            raise Unsupported(f"`{node[1]}` has no numeric value")
        return v
    if tag == "sym":
        raise Unsupported(f"`{node[1]}` has no known value")
    if tag == "opaque":
        raise Unsupported(f"`{_short(node[1])}` is not a simple expression")
    if tag in ("name", "member"):
        if node[1] in env.alias:
            return _eval(env.alias[node[1]], env, values, ctx, depth + 1, calls)
        return _eval(env.term(node, depth), env, values, ctx, depth + 1, calls)
    if tag == "call":
        short = node[1].replace("::", ".").split(".")[-1]
        if short in ctx.mock_names:
            _record_call(node, env, values, ctx, calls)
            return _eval(env.term(node, depth), env, values, ctx, depth + 1, calls)
        if "." in node[1]:
            raise Unsupported(f"method call `{node[1]}()` on an object that runs for real")
        helper = ctx.helpers.get(short)
        if helper is None:
            raise Unsupported(f"`{node[1]}()` runs for real -- its result is not an input")
        args = [_eval(parse(a), env, values, ctx, depth + 1, calls) for a in _split_top(node[2])]
        return execute(helper, args, ctx, values, calls + 1)
    if tag == "neg":
        return -_eval(node[1], env, values, ctx, depth + 1, calls)
    if tag == "bnot":
        return ~_eval(node[1], env, values, ctx, depth + 1, calls)
    if tag == "not":
        return int(not _eval(node[1], env, values, ctx, depth + 1, calls))
    if tag == "bin":
        return _fold(node[1], _eval(node[2], env, values, ctx, depth + 1, calls),
                     _eval(node[3], env, values, ctx, depth + 1, calls))
    if tag == "cmp":
        return int(_compare(node[1], _eval(node[2], env, values, ctx, depth + 1, calls),
                            _eval(node[3], env, values, ctx, depth + 1, calls)))
    if tag == "and":
        return int(bool(_eval(node[1], env, values, ctx, depth + 1, calls))
                   and bool(_eval(node[2], env, values, ctx, depth + 1, calls)))
    if tag == "or":
        return int(bool(_eval(node[1], env, values, ctx, depth + 1, calls))
                   or bool(_eval(node[2], env, values, ctx, depth + 1, calls)))
    if tag == "cond":
        branch = node[2] if _eval(node[1], env, values, ctx, depth + 1, calls) else node[3]
        return _eval(branch, env, values, ctx, depth + 1, calls)
    raise Unsupported(f"expression `{tag}`")


def _eval_display(node, env, values, ctx, depth=0):
    """(display, note) for an expression's value at the end of the path. Symbols
    keep their names (`STATUS_OK`, not 0) -- that is what a tester reads in code."""
    if depth > MAX_DEPTH:
        return None, "expression too deep"
    try:
        t = env.term(node, depth)
    except Unsupported:
        t = None                      # e.g. a helper call: evaluated below
    if t is not None:
        if t[0] == "var":
            v, shown = values.get(t[1], (None, None))
            return display(v, shown, (ctx.variables.get(t[1]) or {}).get("type", "")), None
        if t[0] in ("const", "sym"):
            return t[1], None
        if t[0] == "null":
            return None, None
        if t[0] == "cond":
            try:
                branch = t[2] if _eval(t[1], env, values, ctx) else t[3]
            except Unsupported as exc:
                return None, str(exc)
            return _eval_display(branch, env, values, ctx, depth + 1)
    try:
        return str(_eval(node, env, values, ctx)), None
    except Unsupported as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Executing a helper that runs for real
# ---------------------------------------------------------------------------

MAX_STEPS = 20000        # CFG nodes one helper call may visit (loops included)
MAX_CALLS = 4            # helper-calls-helper nesting
KEY_SEP = "|"


def _split_top(text):
    """Top-level comma split: `a, Bar(b, c)` -> ["a", "Bar(b, c)"]."""
    out, depth, cur = [], 0, ""
    for c in text or "":
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


def _param_names(signature):
    """Parameter names from a START node's `name(int a, const T *p)`, or None."""
    m = re.search(r"\((.*)\)\s*(?:const)?\s*$", signature or "", re.S)
    if not m:
        return None
    inner = m.group(1).strip()
    if inner in ("", "void"):
        return []
    names = []
    for p in _split_top(inner):
        mm = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", p.split("=")[0].strip())
        if not mm:
            return None
        names.append(mm.group(1))
    return names


def helpers_from_cfgs(cfgs):
    """{short name: {"cfg", "params"}} for every function with a CFG. A short name
    two functions share is dropped: executing the wrong body would give a wrong
    expected value, which is worse than none."""
    found, dup = {}, set()
    for key in sorted(cfgs or {}):
        cfg = cfgs[key]
        parts = key.split(KEY_SEP)
        short = (parts[2] if len(parts) > 2 else key).rpartition("::")[2]
        start = next((n for n in cfg.get("nodes", []) if n.get("id") == cfg.get("entry")), {})
        params = _param_names(start.get("rawCode", ""))
        if params is None or not short:
            continue
        if short in found:
            dup.add(short)
            continue
        found[short] = {"cfg": cfg, "params": params}
    for d in dup:
        found.pop(d, None)
    return found


def _loop_parts_full(raw):
    """(init statements, condition, increment statements) of a LOOP_HEAD."""
    text = (raw or "").strip()
    m = re.match(r"^for\s*\((.*)\)\s*$", text, re.S)
    if m:
        parts = _semi_split(m.group(1)) + ["", ""]
        init, cond, incr = parts[0], parts[1], parts[2]
        return ([init] if init.strip() else []), (cond.strip() or "1"), \
            ([incr] if incr.strip() else [])
    init, cond = _loop_parts(raw)
    return init, cond, []


def _next(out):
    for tgt, lab in out:
        if not lab:
            return tgt
    return out[0][0] if out else None


def _take(out, truth):
    want = ("yes", "true") if truth else ("no", "false")
    for tgt, lab in out:
        if str(lab or "").strip().lower() in want:
            return tgt
    raise Unsupported("a branch the graph does not label")


def execute(helper, args, ctx, values, calls=1):
    """Run a helper's CFG with concrete arguments and return its int result.

    Real execution, on our side: conditions are evaluated, loops iterate, a
    `switch` picks its case. Inside, the helper sees its own parameters and
    locals, the globals (at their chosen values) and the stubs (at their chosen
    returns) -- never the caller's parameters. Anything it cannot follow -- a
    read through a pointer or of an array, a statement it cannot read, a helper
    it has no CFG for -- raises Unsupported, and the expected value stays open
    rather than being guessed."""
    if calls > MAX_CALLS:
        raise Unsupported("helper calls nest too deep")
    if len(args) != len(helper["params"]):
        raise Unsupported("argument count does not match the helper")
    env = _Env(ctx, visible={"global", "mock"})
    env.alias = {p: ("num", v) for p, v in zip(helper["params"], args)}
    _, value = _run(helper["cfg"], env, ctx, values, calls)
    if value is None:
        raise Unsupported("the helper returns no value")
    return value


def run_function(cfg, ctx, values):
    """Execute the function under test itself with `values`.

    Returns (exit node id, return value or None, env). `env.alias` then holds
    every local and global the run assigned; `env.record` the stub calls it made,
    with their argument values."""
    env = _Env(ctx)
    env.record = []
    nid, value = _run(cfg, env, ctx, values, 0)
    return nid, value, env


def _run(cfg, env, ctx, values, calls):
    """Walk a CFG concretely from its entry. (exit node id, return value or None)."""
    nodes = {n["id"]: n for n in cfg.get("nodes", [])}
    succ = {}
    for e in cfg.get("edges", []):
        succ.setdefault(e.get("source"), []).append((e.get("target"), e.get("label")))
    active, nid, steps = set(), cfg.get("entry"), 0
    while nid is not None:
        steps += 1
        if steps > MAX_STEPS:
            raise Unsupported("the helper did not finish within the step limit")
        node = nodes.get(nid) or {}
        ntype, raw = node.get("type", ""), node.get("rawCode") or ""
        out = succ.get(nid, [])
        if ntype == "RETURN":
            text = raw.strip().rstrip(";").strip()
            expr = text[len("return"):].strip() if text.startswith("return") else ""
            return nid, (_eval(parse(expr), env, values, ctx, 0, calls) if expr else None)
        if ntype == "END":
            return nid, None
        if ntype == "ACTION":
            for st in statements(raw):
                _exec_statement(st, env, values, ctx, calls)
            nid = _next(out)
        elif ntype == "DECISION":
            nid = _take(out, bool(_eval(parse(raw), env, values, ctx, 0, calls)))
        elif ntype == "LOOP_HEAD":
            init, cond, incr = _loop_parts_full(raw)
            for st in (incr if nid in active else init):
                _exec_statement(st, env, values, ctx, calls)
            active.add(nid)
            truth = bool(_eval(parse(cond), env, values, ctx, 0, calls))
            if not truth:
                active.discard(nid)
            nid = _take(out, truth)
        elif ntype == "SWITCH_HEAD":
            v = _eval(parse(_switch_subject(raw)), env, values, ctx, 0, calls)
            target = default = None
            for tgt, lab in out:
                lab = lab or ""
                if lab.startswith("case ") and target is None and \
                        _eval(parse(_case_value(lab)), env, values, ctx, 0, calls) == v:
                    target = tgt
                elif lab == "default":
                    default = tgt
            nid = target or default or _next([(t, l) for t, l in out if not l])
        else:
            nid = _next(out)                  # START, BREAK, ...
    raise Unsupported("the graph ends without an exit node")


_DECL = re.compile(r"^(?:const\s+|static\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+)*"
                   r"[A-Za-z_][\w:<>]*[\s\*&]+(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?$")


def _exec_statement(stmt, env, values, ctx, calls):
    """Apply one statement concretely inside `_run`.

    A write through a pointer or into an array (`*out = v`, `buf[i] = v`) is
    skipped, not refused: nothing this module evaluates can read it back --
    dereference and indexing are unsupported reads -- so a skipped write can
    never feed a wrong value into a result. Its right side is still evaluated,
    so a stub called there is recorded."""
    s = stmt.strip().rstrip(";").strip().replace("->", ".")
    if not s or s.startswith(("break", "continue", "goto", "case ", "default", "return",
                              "(void)")):
        return
    m = _INCDEC.match(s)
    if m:
        name = m.group("a") or m.group("b")
        step = 1 if (m.group("pre") or m.group("post")) == "++" else -1
        env.alias[name] = ("num", _eval(_base(name), env, values, ctx, 0, calls) + step)
        return
    m = _ASSIGN.match(s)
    if m:
        name = _lhs_name(m.group("lhs"))
        if not name:
            try:
                _eval(parse(m.group("rhs")), env, values, ctx, 0, calls)
            except Unsupported:
                pass
            return
        v = _eval(parse(m.group("rhs")), env, values, ctx, 0, calls)
        op = m.group("op")
        if op != "=":
            v = _fold(op[:-1], _eval(_base(name), env, values, ctx, 0, calls), v)
        env.alias[name] = ("num", v)
        return
    d = _DECL.match(s)
    if d:                                     # `int x` -- declared, not yet set
        env.alias[d.group("name")] = ("opaque", f"{d.group('name')} (uninitialised)")
        return
    try:
        node = parse(s)
    except Unsupported:
        raise Unsupported(f"statement `{_short(s)}` not understood")
    if node[0] == "call":
        # A stub does nothing but is recorded; a helper's result is unused here
        # and its side effects are not followed. Either way the path goes on.
        _record_call(node, env, values, ctx, calls)
        return
    raise Unsupported(f"statement `{_short(s)}` not understood")


def _record_call(node, env, values, ctx, calls):
    """Note a stub call and its argument values on `env.record` (the function
    under test's own run only)."""
    record = getattr(env, "record", None)
    short = node[1].replace("::", ".").split(".")[-1]
    if record is None or short not in ctx.mock_names:
        return
    args = []
    for a in _split_top(node[2]):
        try:
            args.append(_eval(parse(a), env, values, ctx, 0, calls))
        except Unsupported:
            args.append(None)
    record.append((short, args))


def _return_display(ret_node, env, values, ctx):
    raw = (ret_node.get("rawCode") or "").strip().rstrip(";").strip()
    expr = raw[len("return"):].strip() if raw.startswith("return") else ""
    if not expr:
        return None, None
    try:
        node = parse(expr)
    except Unsupported as exc:
        return None, f"return value `{_short(expr)}` not computed: {exc}"
    disp, note = _eval_display(node, env, values, ctx)
    if note:
        return None, f"return value `{_short(expr)}` not computed: {note}"
    if bare_type(ctx.return_type) == "bool" and disp in ("0", "1", True, False):
        disp = "true" if disp in ("1", True) else "false"
    elif isinstance(disp, bool):
        disp = "1" if disp else "0"
    return disp, None


def _stub_calls(calls, values, ctx):
    """[(mock, {param: display})] for the mocks called on the path, first call each,
    with the arguments whose value is known. Out-parameters are left out: the stub
    writes those, the tester does not check them."""
    out, seen = [], set()
    for name, args, env in calls:
        if name in seen:
            continue
        seen.add(name)
        params = ctx.mock_params.get(name) or []
        known = {}
        for i, arg in enumerate(args):
            if i >= len(params):
                break
            p = params[i]
            ptype = p.get("type", "")
            if is_pointer(ptype) and "const" not in ptype:
                continue
            try:
                disp, note = _eval_display(parse(arg), env, values, ctx)
            except Unsupported:
                continue
            if note is None and disp is not None:
                known[p.get("name") or f"arg{i}"] = disp
        out.append((name, known))
    return out


def constants_from_macros(defines, base=None):
    """{NAME: int} from `-DNAME=value` / `NAME=value` strings, numeric values only.

    A macro built from others (`B=(A + 1)`) resolves whatever the order: pending
    ones are retried until a pass adds nothing. `base` holds constants already
    known (enumerators, other defines); only the new names are returned."""
    known = dict(base or {})
    pending = []
    for d in defines or []:
        text = d[2:] if d.startswith("-D") else d
        name, eq, val = text.partition("=")
        if eq and re.match(r"^[A-Za-z_]\w*$", name) and name not in known:
            pending.append((name, val))
    out = {}
    progress = True
    while pending and progress:
        progress, left = False, []
        for name, val in pending:
            try:
                env = _Env(Context({}, constants=known))
                v = _eval(parse(val), env, {}, env.ctx)
            except (Unsupported, RecursionError):
                left.append((name, val))
                continue
            known[name] = out[name] = v
            progress = True
        pending = left
    return out
