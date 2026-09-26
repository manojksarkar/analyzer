"""Findings as something a person reads, and as something a script reads.

Every report has the same shape, whatever was checked -- two documents of one
type, a design against its specification, or one document on its own:

    the documents     which is `−` and which is `+`
    Summary           one row per level: what it checks, whether it agrees, the
                      worst priority -- and the totals per priority
    L1 .. L5          each level's summary table, always shown; its findings
                      underneath, collapsed until opened
    on its own        each document checked against its own rules

The markdown form collapses with `<details>`, so a long report reads as its
summaries until a reader opens the part they care about. The terminal form has no
collapsing: it prints the summaries and the P1/P2 findings, and `--full` lists the
rest. JSON carries all of it for a script.

A change is shown as what changed and nothing else. A declaration that lost two
members prints those two members, not both four-hundred-character declarations; a
list prints the items that changed; a reworded sentence has its changed words
picked out. The same change in several places prints once.
"""
from __future__ import annotations

import difflib
import itertools
import json
import os
import re
import shutil

from .model import (LEVEL_NAMES, LEVELS, P1, P2, P3, P4, PRIORITIES, level_number,
                    normalise_code, normalise_text, priority_rank)


# --- the terminal -------------------------------------------------------------


# Every fancy glyph is one the stock Windows console fonts (Consolas, Lucida
# Console, Courier New) carry: a console with no font fallback draws anything
# else as an empty box. So no check mark, no midline ellipsis, no hook arrow.
_GLYPHS = {
    True: dict(tee="├─ ", last="└─ ", pipe="│  ", blank="   ", sep=" › ", minus="−",
               plus="+", more="…", ok="ok", same="≡", arrow="→", dot=" · "),
    False: dict(tee="|- ", last="`- ", pipe="|  ", blank="   ", sep=" > ", minus="-",
                plus="+", more="...", ok="ok", same="=>", arrow="->", dot=", "),
}

# ANSI SGR codes. `mark` is reverse video: the changed words inside a changed line.
_SGR = {P1: "1;31", P2: "33", P3: "2", P4: "36", "minus": "31", "plus": "32",
        "ok": "32", "dim": "2", "bold": "1", "mark": "7"}

_ROWS = 8           # changed lines shown per finding before --full is needed
_ALSO = 5           # places named on a "same change in" line before --full is needed
_ALIGN = 80         # the column a severity tag is right-aligned to, at most
_COLUMNS = 100      # the width assumed when the terminal will not say

_TOKEN_RE = re.compile(r"\s+|\w+|[^\w\s]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Style:
    """How the terminal report is drawn.

    `color` adds ANSI colour, `fancy` draws the tree with box-drawing characters,
    and `width` wraps long lines to the terminal -- 0 leaves every line whole,
    which is what a file or a grep wants. The default is all three off.
    """

    def __init__(self, color=False, fancy=False, width=0):
        self.color, self.fancy, self.width = color, fancy, width
        self.g = _GLYPHS[bool(fancy)]

    @classmethod
    def for_stream(cls, stream, color="auto"):
        """What `stream` can show. `color` is auto, always or never."""
        tty = bool(getattr(stream, "isatty", lambda: False)())
        drawn = tty or color == "always"
        if color == "auto":
            use = tty and not os.environ.get("NO_COLOR") and _ansi_ok()
        else:
            use = color == "always"
        width = min(max(shutil.get_terminal_size((_COLUMNS, 24)).columns - 1, 60), 160)
        return cls(color=use, fancy=drawn, width=width if drawn else 0)

    def paint(self, text, *names):
        codes = ";".join(_SGR[n] for n in names if n)
        if not self.color or not codes or not text:
            return text
        return "\x1b[%sm%s\x1b[0m" % (codes, text)


def _ansi_ok():
    """True when the console will act on colour codes rather than print them."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)                       # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # Windows 10 understands ANSI once ENABLE_VIRTUAL_TERMINAL_PROCESSING is set.
        return bool(mode.value & 0x0004 or kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


# A line is drawn from tokens: (text, style names). Wrapping works on the tokens,
# so a colour code never counts towards a line's width.

def _tokens(text, *names):
    return [(t, names) for t in _TOKEN_RE.findall(text)]


def _wrap(tokens, width):
    """Tokens broken into lines no wider than `width`; 0 keeps one line."""
    if width <= 0:
        return [tokens]
    lines, line, used = [], [], 0
    for text, names in tokens:
        if text.isspace():
            if line and used + len(text) < width:
                line.append((text, names))
                used += len(text)
            elif line:
                lines.append(line)
                line, used = [], 0
            continue
        if line and used + len(text) > width:
            while line and line[-1][0].isspace():
                line.pop()
            lines.append(line)
            line, used = [], 0
        while len(text) > width:                                  # longer than a line
            lines.append([(text[:width], names)])
            text = text[width:]
        line.append((text, names))
        used += len(text)
    while line and line[-1][0].isspace():
        line.pop()
    if line or not lines:
        lines.append(line)
    return lines


def _draw(tokens, style):
    return "".join(style.paint("".join(t for t, _ in run), *names)
                   for names, run in itertools.groupby(tokens, key=lambda t: t[1]))


def _put(out, style, prefix, tokens, hang=""):
    """Append `tokens` after the tree `prefix`, wrapped; later lines indent by `hang`."""
    width = max(style.width - len(prefix) - len(hang), 24) if style.width else 0
    for n, line in enumerate(_wrap(tokens, width)):
        out.append((style.paint(prefix, "dim") + (hang if n else "") + _draw(line, style)).rstrip())


# --- what changed ---------------------------------------------------------------

def _plain(value):
    """A value as one line of text."""
    if isinstance(value, (list, tuple)):
        return ", ".join(_plain(x) for x in value) if value else "(none)"
    s = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    return s or "(empty)"


def _marks(a, b):
    """Each token of `a` and of `b`, flagged when it is part of the change.

    None when the two have too little in common for the flags to mean anything:
    picking out every word of a rewritten sentence points at nothing.
    """
    ta, tb = _TOKEN_RE.findall(a), _TOKEN_RE.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    if sm.ratio() < 0.5:
        return None
    fa, fb = [False] * len(ta), [False] * len(tb)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            fa[i1:i2] = [True] * (i2 - i1)
            fb[j1:j2] = [True] * (j2 - j1)

    def tidy(tokens, flags):
        # A space is part of the change only between two changed words.
        return [(t, f and (not t.isspace()
                           or (0 < i < len(tokens) - 1 and flags[i - 1] and flags[i + 1])))
                for i, (t, f) in enumerate(zip(tokens, flags))]
    return tidy(ta, fa), tidy(tb, fb)


def _pair_rows(a, b):
    flags = _marks(a, b)
    return [("-", a, flags and flags[0]), ("+", b, flags and flags[1])]


def _diff_items(a_items, b_items, key):
    """Rows for what changed between two item lists, and a tally of it.

    A row is ("-" | "+", text, word flags) or ("gap", unchanged count). A run of
    unchanged items at the end is dropped -- it says nothing -- but one before or
    between changes stays, as a count, so a reader can tell where a change sits.
    """
    ka, kb = [key(x) for x in a_items], [key(x) for x in b_items]
    ops = difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes()
    rows, tally = [], {"changed": 0, "removed": 0, "added": 0}
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            if n < len(ops) - 1:
                rows.append(("gap", i2 - i1))
            continue
        olds, news = a_items[i1:i2], b_items[j1:j2]
        if len(olds) == len(news):                    # one for one: old then new, in pairs
            for old, new in zip(olds, news):
                rows.extend(_pair_rows(old, new))
            tally["changed"] += len(olds)
        else:
            rows.extend(("-", old, None) for old in olds)
            rows.extend(("+", new, None) for new in news)
            both = min(len(olds), len(news))
            tally["changed"] += both
            tally["removed"] += len(olds) - both
            tally["added"] += len(news) - both
    return rows, tally


def _tally(tally, noun=""):
    """`2 members removed, 1 added`."""
    parts = []
    for what in ("changed", "removed", "added"):
        n = tally.get(what, 0)
        if n:
            thing = "%s%s " % (noun, "" if n == 1 else "s") if noun and not parts else ""
            parts.append("%d %s%s" % (n, thing, what))
    return ", ".join(parts)


_ACCESS = ("public", "protected", "private")
_TYPE_DEF_RE = re.compile(r"^(?:typedef\s+)?(?:struct|union|class|enum)\b")


def _block(text):
    """A braced declaration as (head, members, tail), or None when it is not one.

    `class A { public: int f(); int g() { return 1; } };` reads as
    `("class A", ["public: int f();", "public: int g() { return 1; }"], ";")`.
    Each member carries the access label it sits under, so a member that moved
    from public to private shows as a change instead of as nothing. An enum or an
    initialiser list splits on commas instead of semicolons.
    """
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        return None
    head, body, tail = s[:start].strip(), s[start + 1:end], s[end + 1:].strip()
    by_comma = bool(re.search(r"\benum\b", head)) or head.endswith("=")
    members, access, buf, depth = [], "", [], 0

    def emit():
        item = "".join(buf).strip()
        del buf[:]
        if by_comma:
            item = item.rstrip(",").strip()
        if item and item != ";":
            members.append(access + item)

    for i, ch in enumerate(body):
        if (ch == ":" and depth == 0 and not by_comma and "".join(buf).strip() in _ACCESS
                and body[i + 1:i + 2] != ":"):
            access = "".join(buf).strip() + ": "
            del buf[:]
            continue
        buf.append(ch)
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth = max(depth - 1, 0)
            # A function body ends its member at the brace; a nested type runs on to
            # its semicolon (`struct S { int a; } s;`).
            if (ch == "}" and depth == 0 and not by_comma
                    and not _TYPE_DEF_RE.match("".join(buf).strip())):
                emit()
        elif depth == 0 and ch == ("," if by_comma else ";"):
            emit()
    emit()
    return head, members, tail


def _block_view(a, b):
    """(what changed, rows) between two braced declarations, member by member."""
    ba, bb = _block(a), _block(b)
    if not (ba and bb):
        return None
    (ha, ma, ta), (hb, mb, tb) = ba, bb
    rows, what = [], []
    if normalise_code(ha) != normalise_code(hb):
        rows += _pair_rows(ha + " {", hb + " {")
        what.append("opening line changed")
    member_rows, tally = _diff_items(ma, mb, normalise_code)
    rows += member_rows
    if _tally(tally, "member"):
        what.append(_tally(tally, "member"))
    if normalise_code(ta) != normalise_code(tb):
        rows += _pair_rows(("} " + ta).strip(), ("} " + tb).strip())
        what.append("closing line changed")
    return (", ".join(what), rows) if what else None


def _value_view(label, a, b, style):
    """How a value that changed is shown: the headline tokens, and the rows under it.

    A list shows the items that changed, a braced declaration the members that
    changed, and anything else either `old -> new` on one line or, when that
    would not fit, the two values one above the other with the changed words
    picked out.
    """
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        rows, tally = _diff_items([_plain(x) for x in a or []],
                                  [_plain(x) for x in b or []], normalise_text)
        if rows:
            return _tokens("%s: %s" % (label, _tally(tally))), rows
    elif isinstance(a, str) and isinstance(b, str):
        view = _block_view(a, b)
        if view:
            return _tokens("%s: %s" % (label, view[0])), view[1]
    sa, sb = _plain(a), _plain(b)
    if len(label) + len(sa) + len(sb) + 6 <= 72:
        return (_tokens(label + ": ") + _tokens(sa, "minus")
                + _tokens(" %s " % style.g["arrow"]) + _tokens(sb, "plus")), []
    return _tokens(label), _pair_rows(sa, sb)


def _row_lines(out, style, prefix, row):
    g = style.g
    if row[0] == "gap":
        _put(out, style, prefix, _tokens("%s %d unchanged" % (g["more"], row[1]), "dim"))
        return
    if row[0] == "more":
        _put(out, style, prefix, _tokens("%s %d more (--full shows all)" % (g["more"], row[1]),
                                         "dim"))
        return
    sign, text, flags = row
    color = "minus" if sign == "-" else "plus"
    body = ([(t, (color, "mark") if flag else (color,)) for t, flag in flags]
            if flags else _tokens(text, color))
    marker = g["minus"] if sign == "-" else g["plus"]
    _put(out, style, prefix, [(marker + " ", (color,))] + body, hang="  ")


# --- what every renderer is built from ---------------------------------------------

LEVEL_TITLES = {"L1": "Headings", "L2": "Inventory", "L3": "Sections (per unit)",
                "L4": "Views (per table and diagram)", "L5": "Content (per unit, then per view)"}

# What a report calls one entity of a kind.
_NOUN = {"interface": "interface row", "headerdef": "header row",
         "function": "function heading", "unit": "unit", "component": "component",
         "interaction": "dynamic behaviour", "testcase": "test case", "heading": "heading"}

# Fields whose value is a sentence: a change is shown word by word.
_TEXT_FIELDS = {"information", "description", "requirements"}


def _counts(findings):
    """{priority: n} over the findings that count -- a `follows` restates another."""
    out = {p: 0 for p in PRIORITIES}
    for f in findings:
        if f.counted:
            out[f.priority] = out.get(f.priority, 0) + 1
    return out


def _open(findings):
    """Counted findings a rule does not explain -- the ones to act on."""
    return [f for f in findings if f.counted and f.priority != P3]


def _worst(findings):
    fs = _open(findings)
    return min((f.priority for f in fs), key=priority_rank) if fs else ""


def _levels_on(result):
    return [lv for lv in LEVELS if level_number(lv) <= result.max_level]


def _at(findings, level):
    return [f for f in findings if f.level == level]


def _tally_parts(findings):
    c = _counts(findings)
    parts = ["%s %d" % (p, c[p]) for p in (P1, P2, P4) if c.get(p)]
    if c.get(P3):
        parts.append("%d explained" % c[P3])
    return parts


def _group(findings, *keys):
    """Findings grouped by attributes, groups in first-seen order."""
    out = {}
    for f in findings:
        out.setdefault(tuple(getattr(f, k) for k in keys), []).append(f)
    return out


def _change_key(f):
    """What makes two findings the same change, or None for one that never folds."""
    if f.kind != "differs" or (f.left is None and f.right is None):
        return None

    def norm(v):
        if isinstance(v, (list, tuple)):
            return tuple(normalise_text(x) for x in v)
        if isinstance(v, str) and "{" in v:
            return normalise_code(v)
        return normalise_text(v)
    return (f.level, f.view, f.field, f.priority, f.rule, f.follows,
            f.summary.split(": ", 1)[0], norm(f.left), norm(f.right))


def _place(f):
    return f.item or f.unit or f.component or f.path


def _fold(findings):
    """[(finding, [other places])] -- the same change in several places, once."""
    first, out = {}, []
    for f in findings:
        k = _change_key(f)
        if k is not None and k in first:
            first[k][1].append(_place(f))
            continue
        entry = (f, [])
        if k is not None:
            first[k] = entry
        out.append(entry)
    return out


def _check_findings(result, check):
    """The findings a summary row stands for."""
    out = []
    for f in result.findings:
        if f.level != check.level or f.component != check.component:
            continue
        if check.unit and f.unit != check.unit:
            continue
        if f.kind == "differs":
            if f.summary.split(": ", 1)[0] == check.what:
                out.append(f)
        elif check.entity and f.entity == check.entity and not check.follows:
            if check.level == "L1":
                if f.item == check.what:
                    out.append(f)
            elif not check.unit or f.unit == check.unit:
                out.append(f)
    return out


# --- markdown ------------------------------------------------------------------

_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|#])")


def _esc(text):
    """Text safe in a markdown line: nothing in a name turns into formatting."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def _html(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _code(text):
    s = str(text)
    if not s or s == "(empty)":
        return "*empty*"
    tick = "``" if "`" in s else "`"
    pad = " " if tick == "``" else ""
    return "%s%s%s%s%s" % (tick, pad, s, pad, tick)


def _cell(value):
    """A table cell: `|` escaped, a newline kept off the row."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _flag(v):
    return "✓" if v else "✗"


def _num(v):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return _flag(v)
    return str(v)


def _md_words(sa, sb):
    """`old new` as one line with the removed words struck and the added ones bold."""
    ta, tb = _TOKEN_RE.findall(sa), _TOKEN_RE.findall(sb)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(_esc("".join(ta[i1:i2])))
            continue
        gone, came = "".join(ta[i1:i2]).strip(), "".join(tb[j1:j2]).strip()
        if gone:
            out.append("~~%s~~" % _esc(gone))
        if came:
            out.append((" " if gone else "") + "**%s**" % _esc(came))
        if tag != "insert" and ta[i2 - 1:i2] and ta[i2 - 1].isspace():
            out.append(" ")
    return "".join(out)


def _diff_lines(rows):
    out = []
    for row in rows:
        if row[0] == "gap":
            out.append("  … %d unchanged" % row[1])
        elif row[0] == "more":
            out.append("  … %d more" % row[1])
        else:
            out.append("%s %s" % ("-" if row[0] == "-" else "+", row[1]))
    return out


def _rule_word(f):
    if f.explained:
        return "explained"
    return "the rule" if f.breaks else "possible reason"


# The two sides' names while one report is drawn -- "reference" / "compared
# document", or "design" / "specification".
_SIDES = ["reference", "compared document"]


def _md_change(f):
    """(headline, diff block lines or None, a paragraph or None) for one finding."""
    noun = _NOUN.get(f.entity, f.entity or "item")
    if f.kind in ("missing", "extra") and f.item and f.level != "L1"             and f.field != "interactionCall":
        sign, side = ("−", _SIDES[0]) if f.kind == "missing" else ("+", _SIDES[1])
        return "**%s** · %s, only in the %s (%s)" % (_esc(f.item), noun, side, sign), None, None
    if f.kind == "renamed" and f.left is not None:
        return "**%s** → **%s** · %s renamed" % (_esc(f.left), _esc(f.right), noun), None, None
    if f.kind == "order":
        return "**%s** · %s moved: position %s → %s" % (_esc(f.item), noun, f.left, f.right),             None, None
    if f.kind != "differs":
        return _esc(f.summary), None, None
    label = _esc(f.summary.split(": ", 1)[0])
    a, b = f.left, f.right
    if isinstance(a, bool) and isinstance(b, bool):
        side = ("the %s (−)" % _SIDES[0]) if a else ("the %s (+)" % _SIDES[1])
        return "%s: only in %s" % (label, side), None, None
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        rows, tally = _diff_items([_plain(x) for x in a or []],
                                  [_plain(x) for x in b or []], normalise_text)
        if rows:
            return "%s: %s" % (label, _tally(tally) or "order changed"), _diff_lines(rows), None
    elif isinstance(a, str) and isinstance(b, str):
        view = _block_view(a, b)
        if view:
            return "%s: %s" % (label, view[0]), _diff_lines(view[1]), None
    sa, sb = _plain(a), _plain(b)
    if len(sa) + len(sb) <= 70:
        return "%s %s → %s" % (label, _code(sa), _code(sb)), None, None
    if f.field in _TEXT_FIELDS and _marks(sa, sb):
        return "%s reworded" % label, None, _md_words(sa, sb)
    return label, _diff_lines(_pair_rows(sa, sb)), None


class _MdRules:
    """Numbers for a rule that more than one finding in a list carries."""

    def __init__(self, findings):
        seen = {}
        for f in findings:
            if f.rule:
                seen[f.rule] = seen.get(f.rule, 0) + 1
        self.repeated = {r for r, n in seen.items() if n > 1}
        self.numbers = {}

    def note(self, f):
        word = _rule_word(f)
        if f.rule not in self.repeated:
            return "*%s:* %s" % (word, _esc(f.rule))
        if f.rule in self.numbers:
            return "*%s [%d], as above*" % (word, self.numbers[f.rule])
        self.numbers[f.rule] = len(self.numbers) + 1
        return "*%s [%d]:* %s" % (word, self.numbers[f.rule], _esc(f.rule))


def _md_finding(out, f, also=(), indent="", numbered=None):
    """One finding as a bullet: priority, where, what; then how it changed and why."""
    head, block, para = _md_change(f)
    where = f.item or (f.unit if f.entity == "unit" or not f.item else "") or f.component
    lead = "**%s**" % f.priority
    if where and f.kind == "differs":
        lead += " · **%s**" % _esc(where)
    out.append("%s- %s · %s" % (indent, lead, head))
    pad = indent + "  "
    if block:
        out += ["", pad + "```diff"] + [pad + line for line in block] + [pad + "```"]
    if para:
        out += ["", pad + para]
    notes = []
    if also:
        shown = list(also[:8]) + (["and %d more" % (len(also) - 8)] if len(also) > 8 else [])
        notes.append("≡ same change in " + ", ".join("**%s**" % _esc(p) for p in shown))
    if f.rule:
        notes.append(numbered.note(f) if numbered else "*%s:* %s" % (_rule_word(f), _esc(f.rule)))
    if f.follows:
        notes.append("*↳ follows from the %s: shown for detail, not counted*" % _esc(f.follows))
    for note in notes:
        out += ["", pad + note]
    out.append("")


def _md_findings(out, findings, indent=""):
    folded = _fold(sorted(findings, key=lambda f: (f.follows != "", priority_rank(f.priority),
                                                   f.path, f.field)))
    numbered = _MdRules([f for f, _a in folded])
    for f, also in folded:
        _md_finding(out, f, also, indent, numbered)


def _summary_line(findings):
    parts = _tally_parts(findings)
    follows = sum(1 for f in findings if not f.counted)
    if follows:
        parts.append("%d following from above" % follows)
    return " · ".join(parts) if parts else "no findings"


def _details(out, summary_html, body_fn, opened=False):
    out.append("<details%s>" % (" open" if opened else ""))
    out.append("<summary>%s</summary>" % summary_html)
    out.append("")
    body_fn(out)
    out.append("</details>")
    out.append("")


def _md_header(out, result, left_name, right_name, command):
    kind = {"compare": "%s compare" % result.doc_type, "pair": result.doc_type,
            "self": "%s on its own" % result.doc_type}.get(result.mode, result.doc_type)
    out += ["# doccheck — %s" % kind, "", "|  |  |", "|---|---|"]
    if result.mode == "self":
        out.append("| document | `%s` |" % _cell(left_name))
    else:
        out.append("| **−** %s | `%s` |" % (result.sides[0], _cell(left_name)))
        out.append("| **+** %s | `%s` |" % (result.sides[1], _cell(right_name)))
    what = {"compare": "one document against another of the same type",
            "pair": "a SWE.3 design against its SWE.4 specification (V-model)",
            "self": "one document against its own rules"}.get(result.mode, "")
    out.append("| check | **%s**: %s · levels L1–L%d |" % (result.mode, what, result.max_level))
    if command:
        out.append("| command | `%s` |" % _cell(command))
    out.append("")


def _md_summary(out, result, level_what):
    out += ["## Summary", "", "| level | what it checks | result | worst |",
            "|---|---|:-:|:-:|"]
    for lv in _levels_on(result):
        at = _at(result.findings, lv)
        opened, explained = len(_open(at)), _counts(at)[P3]
        res = "✓" if not opened else "✗ %d" % opened
        if explained:
            res += " · %d explained" % explained
        worst = _worst(at)
        out.append("| **%s** %s | %s | %s | %s |" % (
            lv, LEVEL_NAMES[lv], _cell(level_what.get(lv, "")), res,
            "**%s**" % worst if worst == P1 else worst or "·"))
    out.append("")
    parts = _tally_parts(result.findings)
    total = " · ".join(("**%s**" % p) if not p.endswith("explained") else p for p in parts)
    follows = sum(1 for f in result.findings if not f.counted)
    line = total or "**no findings**: the two documents agree on everything compared"
    if follows:
        line += " · %d more shown for detail (they follow from a finding above)" % follows
    out += [line, ""]
    out.append("Every level shows its summary; the details are collapsed. Click a line to "
               "open it." + ("" if result.mode == "self" else
                             " Names are compared as well as counts, so 5 = 5 with different "
                             "names is still ✗."))
    out.append("")
    for note in result.notes:
        out.append("- %s" % _esc(note))
    if result.notes:
        out.append("")


def _md_l1(out, result):
    rows = [c for c in result.checks if c.level == "L1"]
    bad = [c for c in rows if not c.ok]
    if bad:
        out += ["| heading type | − | + | |", "|---|:-:|:-:|---|"]
        for c in bad:
            fs = _check_findings(result, c)
            worst = _worst(fs) or (fs[0].priority if fs else "")
            side = "only in the %s" % (result.sides[0] if c.left else result.sides[1])
            out.append("| %s | %s | %s | **%s** · %s |" % (
                _cell(_esc(c.what)), _flag(c.left), _flag(c.right), worst, side))
        out.append("")
    else:
        used = sum(1 for c in rows if c.left or c.right)
        out += ["Every heading type is on both sides or on neither (%d of the %d types are "
                "used)." % (used, len(rows)), ""]

    def body(o):
        o += ["| heading type | − | + |", "|---|:-:|:-:|"]
        for c in rows:
            o.append("| %s | %s | %s |" % (_cell(_esc(c.what)),
                                           "✓ %d" % c.left if c.left else "—",
                                           "✓ %d" % c.right if c.right else "—"))
        o.append("")
    _details(out, "All %d heading types, with how many of each" % len(rows), body)
    fs = [f for f in _at(result.findings, "L1") if f.rule]
    if fs:
        _details(out, "Details · %s" % _summary_line(fs), lambda o: _md_findings(o, fs))


def _md_l2(out, result):
    rows = [c for c in result.checks if c.level == "L2"]
    if not rows and not _at(result.findings, "L2"):
        out += ["Nothing was compared at this level.", ""]
        return
    if rows:
        out += ["| | − | + | names | |", "|---|--:|--:|:-:|---|"]
    for c in rows:
        label = ("%s › %s" % (c.component, c.what)) if c.component else c.what
        fs = _check_findings(result, c)
        if c.follows:
            note = "*↳ follows from %s*" % _esc(c.follows)
        elif c.skipped:
            note = "*%s*" % _esc(c.skipped)
        else:
            note = "**%s**" % _worst(fs) if _worst(fs) else ""
        names = c.names or ("✓" if c.ok else "✗")
        out.append("| %s | %s | %s | %s | %s |" % (_cell(_esc(label)), _num(c.left),
                                                  _num(c.right), names, note))
    if rows:
        out.append("")
    fs = _at(result.findings, "L2")
    if fs:
        _details(out, "Details · %s" % _summary_line(fs), lambda o: _md_findings(o, fs))


def _units(result, level):
    """(component, unit) in document order, from a level's summary rows."""
    seen = {}
    for c in result.checks:
        if c.level == level:
            seen.setdefault((c.component, c.unit), None)
    return list(seen)


def _md_l3(out, result):
    rows = [c for c in result.checks if c.level == "L3"]
    units = _units(result, "L3")
    skipped = [f for f in result.findings if f.level == "L2" and f.entity == "unit"
               and f.kind in ("missing", "extra")]
    if not rows and not skipped:
        if not _at(result.findings, "L3"):
            out += ["Nothing was compared at this level.", ""]
            return
        units = []
    lists, flags = [], []
    for c in rows:
        target = lists if c.names else flags
        if c.what not in target:
            target.append(c.what)
    head = ["unit"]
    for w in lists:
        head += ["%s −" % w, "+", "names"]
    head += flags
    if units or skipped:
        out.append("| %s |" % " | ".join(_cell(h) for h in head))
        out.append("|%s|" % "|".join(["---"] + ["--:", "--:", ":-:"] * len(lists)
                                     + [":-:"] * len(flags)))
    by_unit = {}
    for c in rows:
        by_unit.setdefault((c.component, c.unit), {})[c.what] = c
    many = len({u for _c, u in units}) != len(units)
    for comp, unit in units:
        cells_ = ["**%s**" % _esc("%s › %s" % (comp, unit) if many else unit)]
        mine = by_unit.get((comp, unit), {})
        for w in lists:
            c = mine.get(w)
            cells_ += ([_num(c.left), _num(c.right), c.names] if c else ["—", "—", ""])
        for w in flags:
            c = mine.get(w)
            if c is None:
                cells_.append("—")
            elif c.left and c.right:
                cells_.append("✓")
            elif not c.left and not c.right:
                cells_.append("— neither")
            else:
                cells_.append("**✗ only in %s**" % ("−" if c.left else "+"))
        out.append("| %s |" % " | ".join(_cell(x) for x in cells_))
    for f in skipped:
        cells_ = ["%s" % _esc(f.item)] + ["—", "—", ""] * len(lists) + [""] * len(flags)
        cells_[-1 if flags else min(3, len(cells_) - 1)] = "*skipped: unit only in %s (L2)*" % (
            "−" if f.kind == "missing" else "+")
        out.append("| %s |" % " | ".join(_cell(x) for x in cells_))
    if units or skipped:
        out.append("")
    for (comp, unit), fs in _group(_at(result.findings, "L3"), "component", "unit").items():
        _details(out, "<b>%s</b> · %s" % (_html(unit or comp), _html(_summary_line(fs))),
                 lambda o, fs=fs: _md_findings(o, fs))


def _row_label(c):
    if c.follows and c.what.startswith(c.follows):
        return "&nbsp;&nbsp;↳ by kind: %s" % _esc(c.what[len(c.follows):].lstrip(" ·"))
    return _esc(c.what)


def _md_l4(out, result):
    checks = [c for c in result.checks if c.level == "L4"]
    findings = _group(_at(result.findings, "L4"), "component", "unit")
    if not (checks or findings):
        out += ["Nothing was compared at this level.", ""]
        return
    by_unit = {}
    for c in checks:
        by_unit.setdefault((c.component, c.unit), []).append(c)
    for key in findings:
        by_unit.setdefault(key, [])
    equal = []
    for (comp, unit), cs in by_unit.items():
        fs = findings.get((comp, unit), [])
        if all(c.ok or c.follows for c in cs) and not fs:
            equal.append((comp, unit))
            continue
        title = "%s › %s" % (comp, unit) if unit else "%s (component)" % comp
        differ = sum(1 for c in cs if not c.ok and not c.follows)

        def body(o, cs=cs, fs=fs):
            if cs:
                o += ["| view | − | + | what differs | |", "|---|--:|--:|---|---|"]
            for c in cs:
                cf = _check_findings(result, c)
                if c.skipped:
                    note = "*%s*" % _esc(c.skipped)
                elif c.follows and not c.ok:
                    note = ""
                else:
                    worst = _worst(cf)
                    expl = sum(1 for f in cf if f.explained)
                    fol = cf and all(f.follows for f in cf)
                    note = ("**%s**" % worst if worst else "") or (
                        "*explained*" if expl else ("*↳ follows*" if fol else ""))
                what = "—" if c.skipped else (c.detail or ("✓" if c.ok else "✗"))
                o.append("| %s | %s | %s | %s | %s |" % (_cell(_row_label(c)), _num(c.left),
                                                         _num(c.right), _cell(_esc(what)), note))
            if cs:
                o.append("")
            if fs:
                _md_findings(o, fs)
        _details(out, "<b>%s</b> · %d of %d views differ · %s" % (
            _html(title), differ, len([c for c in cs if not c.follows]),
            _html(_summary_line(fs))), body)
    if equal:
        names = ", ".join((u or "%s (component)" % c) for c, u in equal)
        _details(out, "%d %s: all views equal" % (len(equal), "place" if len(equal) == 1
                                                  else "places"),
                 lambda o: o.extend([_esc(names), ""]))


def _md_l5(out, result):
    fs5 = _at(result.findings, "L5")
    by_unit = _group(fs5, "component", "unit")
    for (comp, unit), fs in by_unit.items():
        title = "%s › %s" % (comp, unit) if unit else comp

        def body(o, fs=fs, title=title):
            for (view,), vfs in _group(fs, "view").items():
                shown = [f for f in vfs if not f.explained]
                explained = [f for f in vfs if f.explained]

                def vbody(p, shown=shown, explained=explained):
                    _md_findings(p, shown)
                    if explained:
                        def ebody(q, explained=explained):
                            q += ["| where | what | rule |", "|---|---|---|"]
                            for f, also in _fold(explained):
                                where = _place(f) + (" and %d more" % len(also) if also else "")
                                q.append("| %s | %s | %s |" % (
                                    _cell(_esc(where)), _cell(_md_change(f)[0]),
                                    _cell(_esc(f.rule))))
                            q.append("")
                        _details(p, "<i>Explained by a rule · %d</i>" % len(explained), ebody)
                _details(o, "<b>%s › %s</b> · %s" % (_html(title), _html(view or "content"),
                                                     _html(_summary_line(vfs))), vbody)
        _details(out, "<b>%s</b> · %s" % (_html(title), _html(_summary_line(fs))), body)
    quiet = [(k, n) for k, n in _compared_units(result).items() if k not in by_unit]
    if quiet:
        names = ", ".join("%s (%d)" % (u or c, n) for (c, u), n in quiet)
        _details(out, "%d %s: all content equal" % (len(quiet), "unit" if len(quiet) == 1
                                                    else "units"),
                 lambda o: o.extend(["Matched items compared, per unit: " + _esc(names), ""]))
    if not fs5 and not quiet:
        out += ["Nothing was compared at this level.", ""]


def _compared_units(result):
    out = {}
    for (comp, unit, _view), n in result.compared.items():
        out[(comp, unit)] = out.get((comp, unit), 0) + n
    return out


def _md_self_block(out, findings):
    for lv in LEVELS:
        at = _at(findings, lv)
        if not at:
            continue
        for (comp, unit), fs in _group(at, "component", "unit").items():
            title = " › ".join(x for x in (comp, unit) if x) or "document"
            _details(out, "<b>%s %s</b> · %s" % (lv, _html(title), _html(_summary_line(fs))),
                     lambda o, fs=fs: _md_findings(o, fs))


def _md_own(out, result):
    out += ["## Each document on its own", "", "| | result |", "|---|---|"]
    for sign, role, fs in (("−", result.sides[0], result.self_left),
                           ("+", result.sides[1], result.self_right)):
        out.append("| **%s** %s | %s |" % (sign, role, _summary_line(fs) if fs else "clean"))
    out.append("")
    for sign, role, fs in (("−", result.sides[0], result.self_left),
                           ("+", result.sides[1], result.self_right)):
        if fs:
            def body(o, fs=fs):
                _md_self_block(o, fs)
            _details(out, "<b>%s %s</b> · %s" % (sign, _html(role), _html(_summary_line(fs))),
                     body)


_LEGEND = [
    "| priority | meaning |", "|---|---|",
    "| P1 blocker | breaks a documented rule: a missing unit, a wrong Direction or Data Type, "
    "broken IDs, a design and a spec that do not pair |",
    "| P2 review | a real difference a person has to judge |",
    "| P3 explained | a documented rule produces it; listed with the rule, never counted as a "
    "defect |",
    "| P4 cosmetic | order and wording only |", "",
    "| level | question |", "|---|---|",
    "| L1 headings | Is every kind of heading there? |",
    "| L2 inventory | Are the same components, units and dynamic behaviours there, by name? |",
    "| L3 sections | Does each unit have the same function headings and sub-sections? |",
    "| L4 views | Does each table and diagram have the same rows and images? |",
    "| L5 content | Do the matched rows say the same thing? |", "",
    "`−` is the first document and `+` the second. `≡` means the same change appears in "
    "other places too; it is printed once. *↳ follows* marks a finding that restates one "
    "found at a higher level: shown for its detail, not counted again. A *possible reason* "
    "is a documented rule that would produce the difference but cannot be proved from the "
    "documents; an *explained* one is fully accounted for.", "",
]


def markdown(result, left_name, right_name="", self_left=None, self_right=None,
             level_what=None, command=""):
    """The long-form report: summaries shown, details collapsed."""
    if self_left is not None:
        result.self_left = self_left
    if self_right is not None:
        result.self_right = self_right
    level_what = level_what or getattr(result, "level_what", {}) or {}
    _SIDES[:] = list(result.sides)
    out = []
    _md_header(out, result, left_name, right_name, command)
    _md_summary(out, result, level_what)
    out += ["---", ""]
    if result.mode == "self":
        for lv in _levels_on(result):
            out += ["## %s · %s" % (lv, LEVEL_TITLES[lv].split(" (")[0]), ""]
            at = _at(result.findings, lv)
            if at:
                _md_self_block(out, at)
            else:
                out += ["Nothing to report.", ""]
    else:
        renderers = {"L1": _md_l1, "L2": _md_l2, "L3": _md_l3, "L4": _md_l4, "L5": _md_l5}
        for lv in _levels_on(result):
            out += ["## %s · %s" % (lv, LEVEL_TITLES[lv]), ""]
            renderers[lv](out, result)
        out += ["---", ""]
        _md_own(out, result)
    out += ["---", ""]
    _details(out, "<b>How to read this</b>", lambda o: o.extend(_LEGEND))
    return "\n".join(out).rstrip() + "\n"


# --- the terminal -----------------------------------------------------------------

def _entry_of(f):
    """(group, entry) for a finding: its component, and where under it."""
    if f.level == "L1" or not f.component:
        return "(document)", (f.item,) if f.item else ()
    rest = tuple(x for x in (f.unit, f.item if f.item != f.unit else "") if x)
    return f.component, rest


def _t_view(f, style):
    """(headline tokens, rows) for one finding on a terminal."""
    if f.kind == "differs" and isinstance(f.left, bool) and isinstance(f.right, bool):
        return _tokens("%s: only in the %s" % (f.summary.split(": ", 1)[0],
                                               _SIDES[0] if f.left else _SIDES[1])), []
    if f.kind == "differs" and (f.left is not None or f.right is not None):
        return _value_view(f.summary.split(": ", 1)[0], f.left, f.right, style)
    return _tokens(f.summary), []


class _Rules:
    """Numbers for the rules that explain more than one finding, printed in full once."""

    def __init__(self, findings):
        seen = {}
        for f in findings:
            if f.rule:
                seen[f.rule] = seen.get(f.rule, 0) + 1
        self.repeated = {rule for rule, n in seen.items() if n > 1}
        self.numbers = {}

    def ref(self, rule):
        if rule not in self.repeated:
            return None, True
        if rule in self.numbers:
            return self.numbers[rule], False
        self.numbers[rule] = len(self.numbers) + 1
        return self.numbers[rule], True


def _heading(style, prefix, label, priority):
    """One tree line: the label, and the priority right-aligned when there is one."""
    line = style.paint(prefix, "dim") + _draw(label, style)
    if not priority:
        return line.rstrip()
    used = len(prefix) + sum(len(t) for t, _ in label)
    col = min(style.width or _ALIGN, _ALIGN)
    return line + " " * max(col - used - len(priority), 2) + style.paint(priority, priority)


def _t_item(out, style, prefix, f, also, rules, full, entry_rank):
    g = style.g
    head, rows = _t_view(f, style)
    head = list(head)
    if priority_rank(f.priority) > entry_rank:
        head += _tokens(" (%s)" % f.priority, f.priority)
    if f.follows:
        head += _tokens(" ↳ follows from the %s" % f.follows, "dim")
    _put(out, style, prefix, head, hang="  ")
    if not full and len(rows) > _ROWS:
        cut = _ROWS
        if rows[cut - 1][0] == "-" and rows[cut][0] == "+":        # never split an old from its new
            cut += 1
        hidden = sum(1 for r in rows[cut:] if r[0] in "-+")
        rows = rows[:cut] + ([("more", hidden)] if hidden else [])
    for row in rows:
        _row_lines(out, style, prefix + "  ", row)
    if f.rule:
        number, first = rules.ref(f.rule)
        word = _rule_word(f)
        if first:
            text = "%s [%d]: %s" % (word, number, f.rule) if number else "%s: %s" % (word, f.rule)
        else:
            text = "%s [%d], as above" % (word, number)
        _put(out, style, prefix, _tokens(text, "dim"), hang="      ")
    if also:
        shown = also if full or len(also) <= _ALSO else also[:_ALSO]
        text = "%s same change in %s" % (g["same"], ", ".join(shown))
        if len(shown) < len(also):
            text += " and %d more" % (len(also) - len(shown))
        _put(out, style, prefix, _tokens(text, "dim"), hang="  ")


def _t_tree(findings, style, full):
    """Findings drawn as component, then unit and item, then what changed -- worst first."""
    g = style.g
    folded = _fold(sorted(findings, key=lambda f: f.sort_key()))
    groups = {}
    for f, also in folded:
        group, entry = _entry_of(f)
        groups.setdefault(group, {}).setdefault(entry, []).append((f, also))
    rules = _Rules([f for f, _a in folded])

    def rank(items):
        return min(priority_rank(f.priority) for f, _a in items)

    out = []
    for group in sorted(groups, key=lambda k: rank([x for v in groups[k].values() for x in v])):
        entries = groups[group]
        own = entries.pop((), [])
        rest = sorted(entries.items(), key=lambda kv: rank(kv[1]))
        worst = PRIORITIES[rank(own)] if own else ""
        out.append(_heading(style, " ", _tokens(group, "bold"), worst))
        body = " " + (g["pipe"] if rest else g["blank"]) + "  "
        for f, also in own:
            _t_item(out, style, body, f, also, rules, full, rank(own))
        if own and rest:
            out.append(style.paint(" " + g["pipe"], "dim").rstrip())
        for n, (entry, items) in enumerate(rest):
            last = n == len(rest) - 1
            label = []
            for i, part in enumerate(entry):
                if i:
                    label += _tokens(g["sep"])
                label += _tokens(part, "bold") if i == len(entry) - 1 else _tokens(part)
            out.append(_heading(style, " " + (g["last"] if last else g["tee"]), label,
                                PRIORITIES[rank(items)]))
            body = " " + (g["blank"] if last else g["pipe"]) + "  "
            for f, also in items:
                _t_item(out, style, body, f, also, rules, full, rank(items))
            if not last:
                out.append(style.paint(" " + g["pipe"], "dim").rstrip())
        out.append("")
    return out


def _names(a, b, style):
    """Two paths cut down to what tells them apart."""
    pa = (a or "").replace("\\", "/").split("/")
    pb = (b or "").replace("\\", "/").split("/")
    if pa[-1] != pb[-1] or a == b:
        return pa[-1], pb[-1]
    i = 2                                         # same file name: find the directory that differs
    while i <= min(len(pa), len(pb)) and pa[-i] == pb[-i]:
        i += 1
    if i > min(len(pa), len(pb)):
        return a, b

    def cut(p):
        return "/".join([p[-i]] + ([style.g["more"]] if i > 2 else []) + [p[-1]])
    return cut(pa), cut(pb)


def _sides(style, left, right):
    """The two documents, each under the sign its changes are drawn with."""
    (lw, ln), (rw, rn) = left, right
    ln, rn = _names(ln, rn, style)
    pad = max(len(lw), len(rw))
    return [" %s %s  %s" % (style.paint(style.g["minus"], "minus"), lw.ljust(pad), ln),
            " %s %s  %s" % (style.paint(style.g["plus"], "plus"), rw.ljust(pad), rn)]


def _ladder(result, style):
    """`L1 ok  L2 2  ...` -- how far down the two documents agree."""
    parts = []
    for lv in _levels_on(result):
        at = _open(_at(result.findings, lv))
        if not at:
            parts.append("%s %s" % (lv, style.paint(style.g["ok"], "ok")))
        else:
            parts.append("%s %s" % (lv, style.paint(str(len(at)), _worst(at))))
    return "   ".join(parts)


def _tallies(findings, style):
    parts = _tally_parts(findings)
    if not parts:
        return style.paint("no findings", "ok")
    painted = []
    for p in parts:
        key = p.split()[0] if p[0] == "P" else P3
        painted.append(style.paint(p, key))
    return style.g["dot"].join(painted)


def _t_checks(out, result, level, style):
    """The summary rows of one level that disagree, one line each."""
    for c in result.checks:
        if c.level != level or c.ok or c.follows:
            continue
        where = " › ".join(x for x in (c.component, c.unit) if x)
        label = "%s%s" % ((where + " › ") if where else "", c.what)
        counts = "" if c.left is None and c.right is None else "%s %s %s" % (
            _num(c.left), style.g["arrow"], _num(c.right))
        text = "   %s  %s  %s" % (label, counts, c.skipped or c.detail or "")
        _put(out, style, "", _tokens(text.rstrip()), hang="      ")


def text(result, left_name, right_name="", self_left=None, self_right=None,
         style=None, full=False, level_what=None):
    """The terminal report: the ladder, each level's disagreeing rows and findings.

    P3 and P4 findings, and findings that follow from one above, are counted but
    listed only with `full` -- which also lifts the cap on how many changed lines
    one finding prints.
    """
    style = style or Style()
    if self_left is not None:
        result.self_left = self_left
    if self_right is not None:
        result.self_right = self_right
    level_what = level_what or getattr(result, "level_what", {}) or {}
    _SIDES[:] = list(result.sides)
    if result.mode == "self":
        out = [" %s  %s, checked against itself" % (style.paint(os.path.basename(left_name),
                                                                "bold"), result.doc_type)]
    else:
        out = _sides(style, (result.sides[0], left_name), (result.sides[1], right_name))
    ladder, tallies = _ladder(result, style), _tallies(result.findings, style)
    line = " %s     %s" % (ladder, tallies)
    if style.width and len(_ANSI_RE.sub("", line)) > style.width:     # a narrow terminal
        out += ["", " " + ladder, " " + tallies, ""]
    else:
        out += ["", line, ""]
    if not result.findings:
        out += [" " + style.paint("nothing to report at any level", "ok"), ""]
    hidden = 0
    for lv in _levels_on(result):
        at = _at(result.findings, lv)
        shown = at if full else [f for f in at if f.counted and f.priority in (P1, P2)]
        hidden += len(at) - len(shown)
        bad_rows = any(c.level == lv and not c.ok and not c.follows for c in result.checks)
        if not shown and not bad_rows:
            continue
        out.append(" %s" % style.paint("%s %s — %s" % (lv, LEVEL_NAMES[lv],
                                                      level_what.get(lv, "")), "bold"))
        if result.mode != "self":
            _t_checks(out, result, lv, style)
        out.append("")
        if shown:
            out += _t_tree(shown, style, full)
    if result.mode != "self":
        for title, fs in (("the %s, checked against itself" % result.sides[0], result.self_left),
                          ("the %s, checked against itself" % result.sides[1], result.self_right)):
            if fs:
                shown = fs if full else [f for f in fs if f.priority in (P1, P2)]
                hidden += len(fs) - len(shown)
                out += [" %s  %s" % (style.paint(title, "bold"), _tallies(fs, style)), ""]
                out += _t_tree(shown, style, full)
    for note in result.notes:
        _put(out, style, " ", _tokens("note: " + note, "dim"), hang="       ")
    if hidden and not full:
        out.append(style.paint(" %d finding%s not listed: P3 explained, P4 cosmetic, or "
                               "restating one above (--full lists them)"
                               % (hidden, "" if hidden == 1 else "s"), "dim"))
    text_ = "\n".join(out).rstrip() + "\n"
    return text_ if style.fancy else _ascii(text_)


# The glyphs the report itself draws, and what a plain (non-terminal) stream gets
# instead: a pipe or a file stays ASCII, so it still greps.
_ASCII = {"−": "-", "·": ",", "→": "->", "↔": "<->", "›": ">", "✓": "ok", "✗": "x",
          "↳": "->", "—": "-", "…": "...", "≡": "=>", "│": "|", "├": "|", "└": "`",
          "─": "-"}


def _ascii(text):
    for glyph, plain in _ASCII.items():
        text = text.replace(glyph, plain)
    return text


def summary_line(result):
    c = _counts(result.findings)
    return "%d finding(s): %s" % (len(result.findings),
                                  ", ".join("%d %s" % (c[p], p) for p in PRIORITIES))


# --- json ---------------------------------------------------------------------------

SCHEMA = "doccheck/2"


def _finding_dict(f):
    d = dict(f.__dict__)
    d["counted"] = f.counted
    return d


def to_json(result, left_name, right_name="", self_left=None, self_right=None,
            level_what=None):
    if self_left is not None:
        result.self_left = self_left
    if self_right is not None:
        result.self_right = self_right
    level_what = level_what or getattr(result, "level_what", {}) or {}
    levels = {}
    for lv in _levels_on(result):
        at = _at(result.findings, lv)
        c = _counts(at)
        levels[lv] = {"what": level_what.get(lv, ""), "open": len(_open(at)),
                      "worst": _worst(at), **{p: c[p] for p in PRIORITIES},
                      "follows": sum(1 for f in at if not f.counted)}
    c = _counts(result.findings)
    payload = {
        "schema": SCHEMA,
        "mode": result.mode,
        "docType": result.doc_type,
        "maxLevel": result.max_level,
        "left": {"role": result.sides[0], "path": left_name},
        "right": {"role": result.sides[1], "path": right_name},
        "summary": {"findings": len(result.findings), "open": len(_open(result.findings)),
                    **{p: c[p] for p in PRIORITIES}, "levels": levels},
        "notes": list(result.notes),
        "inventory": {
            kind: {"left": result.left_total.get(kind, 0),
                   "right": result.right_total.get(kind, 0),
                   "matched": result.matched.get(kind, 0),
                   "score": round(result.score(kind), 4)}
            for kind in sorted(set(result.left_total) | set(result.right_total))
        },
        "checks": [dict(c.__dict__) for c in result.checks],
        "findings": [_finding_dict(f) for f in result.findings],
        "selfChecks": {"left": [_finding_dict(f) for f in result.self_left],
                       "right": [_finding_dict(f) for f in result.self_right]},
    }
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n"
