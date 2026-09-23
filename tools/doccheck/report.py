"""Findings as something a person reads, and as something a script reads.

The markdown form leads with the ladder, because the first question is always
"how far down did it get before it stopped agreeing" -- if the unit inventory
does not match, nothing below it is worth reading yet.

The terminal form shows a change as what changed and nothing else. A declaration
that lost two members prints those two members, not both four-hundred-character
declarations side by side; a test step that was reworded prints that step, with
the changed words picked out. Findings sit under the component they belong to,
worst first, and the same change in two places prints once. Colour and
box-drawing are used only where the terminal can show them -- a pipe or a file
gets plain ASCII, unwrapped, so it still greps.
"""
from __future__ import annotations

import difflib
import itertools
import json
import os
import re
import shutil

from .model import HIGH, INFO, LOW, MEDIUM, normalise_code, normalise_text

_LADDER = [
    ("L0", "document shape"),
    ("L1", "unit inventory"),
    ("L2", "per unit"),
    ("L3", "per row"),
    ("L4", "dynamic behaviour"),
]


def _counts(findings):
    out = {}
    for f in findings:
        out[f.severity] = out.get(f.severity, 0) + 1
    return out


def summary_line(result):
    c = _counts(result.findings)
    return "%d finding(s): %d high, %d medium, %d low, %d info" % (
        len(result.findings), c.get(HIGH, 0), c.get(MEDIUM, 0), c.get(LOW, 0), c.get(INFO, 0))


def markdown(result, left_name, right_name, self_left=None, self_right=None):
    out = []
    add = out.append
    add("# Document comparison")
    add("")
    add("| | document |")
    add("|---|---|")
    add("| reference | `%s` |" % left_name)
    add("| compared | `%s` |" % right_name)
    add("")
    add(summary_line(result))
    add("")

    add("## Ladder")
    add("")
    add("| level | what | high | medium | low | info |")
    add("|---|---|---|---|---|---|")
    for level, label in _LADDER:
        at = [f for f in result.findings if f.level == level]
        c = _counts(at)
        add("| %s | %s | %d | %d | %d | %d |" % (
            level, label, c.get(HIGH, 0), c.get(MEDIUM, 0), c.get(LOW, 0), c.get(INFO, 0)))
    add("")

    add("## Inventory")
    add("")
    add("| kind | reference | compared | matched | score |")
    add("|---|---|---|---|---|")
    for kind in sorted(set(result.left_total) | set(result.right_total)):
        add("| %s | %d | %d | %d | %.0f%% |" % (
            kind, result.left_total.get(kind, 0), result.right_total.get(kind, 0),
            result.matched.get(kind, 0), 100 * result.score(kind)))
    add("")

    for name, findings in (("Reference document, checked against itself", self_left or []),
                           ("Compared document, checked against itself", self_right or [])):
        if findings:
            add("## %s" % name)
            add("")
            for f in findings:
                add("- **%s** — %s" % (f.path or "(document)", f.summary))
            add("")

    add("## Findings")
    add("")
    if not result.findings:
        add("Nothing to report: the two documents agree on everything compared.")
        return "\n".join(out) + "\n"

    current = None
    for f in result.findings:
        if f.severity != current:
            current = f.severity
            add("")
            add("### %s" % {HIGH: "High", MEDIUM: "Medium", LOW: "Low", INFO: "Informational"}[f.severity])
            add("")
        where = f.path or "(document)"
        add("- `%s` — %s" % (where, f.summary))
        if f.rule:
            add("  - explained by: %s" % f.rule)
    add("")
    return "\n".join(out) + "\n"


# --- the terminal -------------------------------------------------------------

_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3}

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
_SGR = {HIGH: "1;31", MEDIUM: "33", LOW: "36", INFO: "2", "minus": "31", "plus": "32",
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


# --- one finding ------------------------------------------------------------------

_ONLY_RE = re.compile(r"^(\S+) .* is in the (reference|other document) and not in the "
                      r"(?:reference|other document)$")


def _only(f):
    """(entity kind, side) for the ladder's own 'only on one side' wording, else None."""
    if f.kind not in ("missing", "extra"):
        return None
    m = _ONLY_RE.match(f.summary or "")
    return m and (m.group(1), "reference" if m.group(2) == "reference" else "compared")


def _view(f, style):
    """(headline tokens, rows) for one finding."""
    summary = f.summary or ""
    if ": " in summary and " -> " in summary and (f.left is not None or f.right is not None):
        return _value_view(summary.split(": ", 1)[0], f.left, f.right, style)
    if f.kind == "differs" and f.left is not None and f.right is not None:
        return _tokens(summary), _pair_rows(_plain(f.left), _plain(f.right))
    return _tokens(summary), []


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
    return f.field, f.severity, f.rule, f.summary.split(": ", 1)[0], norm(f.left), norm(f.right)


def _where(f):
    """(group, entry) for a finding: its component, and the rest of its path."""
    path = f.path or ""
    if not path or path == "(document)":
        return "(document)", ()
    parts = tuple(p for p in path.split(" / ") if p)
    if f.level == "L0":
        return "(document)", parts
    return parts[0], parts[1:]


def _items(findings, style):
    """An entry's findings as display items, one-side findings merged.

    An item is a dict: severity, the finding it came from, and either headline
    tokens and rows, or -- for the ladder's 'only on one side' findings -- the
    entity kinds found on that side, each with its rule. `interface` and
    `function` both missing at one path read as one line.
    """
    items, merged = [], {}
    for f in findings:
        only = _only(f)
        if only:
            key = (f.kind, only[1], f.severity)
            if key in merged:
                merged[key]["kinds"].append((only[0], f.rule))
                continue
            item = merged[key] = dict(severity=f.severity, finding=f, side=only[1],
                                      sign=f.kind, kinds=[(only[0], f.rule)])
        else:
            head, rows = _view(f, style)
            item = dict(severity=f.severity, finding=f, head=head, rows=rows, rule=f.rule)
        items.append(item)
    return items


class _Rules:
    """Numbers for the rules that explain more than one finding.

    A rule is a sentence or two, and twenty findings explained by one rule would
    print it twenty times. A rule that repeats is printed in full once, as
    `rule [1]: ...`, and referred to as `[1]` everywhere after.
    """

    def __init__(self, findings):
        seen = {}
        for f in findings:
            if f.rule:
                seen[f.rule] = seen.get(f.rule, 0) + 1
        self.repeated = {rule for rule, n in seen.items() if n > 1}
        self.numbers = {}

    def ref(self, rule):
        """(number or None, first time this rule is shown)."""
        if rule not in self.repeated:
            return None, True
        if rule in self.numbers:
            return self.numbers[rule], False
        self.numbers[rule] = len(self.numbers) + 1
        return self.numbers[rule], True


def _rule_lines(out, style, prefix, rule, number, first):
    if first:
        text = "rule [%d]: %s" % (number, rule) if number else "rule: " + rule
    else:
        text = "rule [%d], as above" % number
    _put(out, style, prefix, _tokens(text, "dim"), hang="      ")


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


class _Draw:
    """What drawing one tree needs besides the findings: the style, the options,
    and the state that runs across entries (folded places, rule numbers)."""

    def __init__(self, style, full, sides, also, rules):
        self.style, self.full, self.sides, self.also, self.rules = style, full, sides, also, rules


def _item_lines(out, d, prefix, item, entry_rank):
    style, g = d.style, d.style.g
    notes = []                                                  # (number, rule, first)
    if "kinds" in item:
        color = "minus" if item["sign"] == "missing" else "plus"
        side = d.sides[0] if item["side"] == "reference" else d.sides[1]
        named = []
        for kind, rule in item["kinds"]:
            number, first = d.rules.ref(rule) if rule else (None, False)
            named.append(kind + (" [%d]" % number if number else ""))
            if rule and first and (number, rule, True) not in notes:
                notes.append((number, rule, True))
        marker = g["minus"] if item["sign"] == "missing" else g["plus"]
        head = _tokens("%s only in the %s: %s" % (marker, side, ", ".join(named)), color)
        rows = []
    else:
        head, rows = list(item["head"]), item["rows"]
        if item["rule"]:
            number, first = d.rules.ref(item["rule"])
            notes.append((number, item["rule"], first))
    if _RANK.get(item["severity"], 9) > entry_rank:             # quieter than its entry
        head = head + _tokens(" (%s)" % item["severity"], item["severity"])
    _put(out, style, prefix, head, hang="  ")

    if not d.full and len(rows) > _ROWS:
        cut = _ROWS
        if rows[cut - 1][0] == "-" and rows[cut][0] == "+":     # never split an old from its new
            cut += 1
        hidden = sum(1 for r in rows[cut:] if r[0] in "-+")
        rows = rows[:cut] + ([("more", hidden)] if hidden else [])
    for row in rows:
        _row_lines(out, style, prefix + "  ", row)

    for number, rule, first in notes:
        _rule_lines(out, style, prefix + ("  " if "kinds" in item else ""), rule, number, first)
    places = d.also.get(id(item["finding"]), [])
    if places:
        shown = places if d.full or len(places) <= _ALSO else places[:_ALSO]
        text = "%s same change in %s" % (g["same"], ", ".join(shown))
        if len(shown) < len(places):
            text += " and %d more" % (len(places) - len(shown))
        _put(out, style, prefix, _tokens(text, "dim"), hang="  ")


def _heading(style, prefix, label, severity):
    """One tree line: the label, and the severity right-aligned when there is one."""
    line = style.paint(prefix, "dim") + _draw(label, style)
    if not severity:
        return line.rstrip()
    used = len(prefix) + sum(len(t) for t, _ in label)
    col = min(style.width or _ALIGN, _ALIGN)
    tag = severity.upper()
    return line + " " * max(col - used - len(tag), 2) + style.paint(tag, severity)


def _tree(findings, style, full, sides=("reference", "compared document")):
    """Findings drawn as component, then entry, then what changed -- worst first."""
    g = style.g

    # The same change in several places prints once, under the first of them.
    first, kept, also = {}, [], {}
    for f in findings:
        key = _change_key(f)
        if key is not None and key in first:
            canon = first[key]
            group, entry = _where(f)
            label = entry if group == _where(canon)[0] else (group,) + entry
            also.setdefault(id(canon), []).append(g["sep"].join(label) or group)
            continue
        if key is not None:
            first[key] = f
        kept.append(f)

    groups = {}
    for f in kept:
        group, entry = _where(f)
        groups.setdefault(group, {}).setdefault(entry, []).append(f)

    def rank(fs):
        return min(_RANK.get(f.severity, 9) for f in fs)

    def worst(fs):
        return min((f.severity for f in fs), key=lambda s: _RANK.get(s, 9))

    d = _Draw(style, full, sides, also, _Rules(kept))
    out = []
    for group in sorted(groups, key=lambda k: rank([f for fs in groups[k].values() for f in fs])):
        entries = groups[group]
        own = entries.pop((), [])
        rest = sorted(entries.items(), key=lambda kv: rank(kv[1]))
        out.append(_heading(style, " ", _tokens(group, "bold"), own and worst(own)))
        body = " " + (g["pipe"] if rest else g["blank"]) + "  "
        for item in _items(own, style):
            _item_lines(out, d, body, item, rank(own))
        if own and rest:
            out.append(style.paint(" " + g["pipe"], "dim").rstrip())
        for n, (entry, fs) in enumerate(rest):
            last = n == len(rest) - 1
            label = []
            for i, part in enumerate(entry):
                if i:
                    label += _tokens(g["sep"])
                label += _tokens(part, "bold") if i == len(entry) - 1 else _tokens(part)
            out.append(_heading(style, " " + (g["last"] if last else g["tee"]), label, worst(fs)))
            body = " " + (g["blank"] if last else g["pipe"]) + "  "
            for item in _items(fs, style):
                _item_lines(out, d, body, item, rank(fs))
            if not last:
                out.append(style.paint(" " + g["pipe"], "dim").rstrip())
        out.append("")
    return out


# --- the whole report ---------------------------------------------------------------

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


def _ladder(findings, style):
    """`L0 ok  L1 ok  L2 9  ...` -- how far down the two documents agree."""
    parts = []
    for level, _label in _LADDER:
        at = [f for f in findings if f.level == level and f.severity != INFO]
        if not at:
            parts.append("%s %s" % (level, style.paint(style.g["ok"], "ok")))
        else:
            sev = min((f.severity for f in at), key=lambda s: _RANK.get(s, 9))
            parts.append("%s %s" % (level, style.paint(str(len(at)), sev)))
    return "   ".join(parts)


def _tallies(findings, style, total=True):
    """`9 findings: 2 high · 7 medium`, each count in its severity's colour."""
    if not findings:
        return style.paint("no findings", "ok")
    c = _counts(findings)
    parts = [style.paint("%d %s" % (c[s], s), s) for s in (HIGH, MEDIUM, LOW, INFO) if c.get(s)]
    line = style.g["dot"].join(parts)
    if total:
        line = "%d finding%s: %s" % (len(findings), "" if len(findings) == 1 else "s", line)
    return line


def _footer(style, findings, full):
    info = sum(1 for f in findings if f.severity == INFO)
    if full or not info:
        return []
    return [style.paint(" %d info finding%s not shown (--full lists them)"
                        % (info, "" if info == 1 else "s"), "dim")]


def _shown(findings, full):
    return list(findings) if full else [f for f in findings if f.severity != INFO]


def text(result, left_name, right_name, self_left=None, self_right=None,
         style=None, full=False):
    """The terminal report of a comparison.

    The two documents, the ladder on one line, then what changed, grouped under
    the component it belongs to. INFO findings -- advisory, or fully explained by
    a documented rule -- are counted but listed only with `full`, which also
    lifts the cap on how many changed lines one finding prints.
    """
    style = style or Style()
    out = _sides(style, ("reference", left_name), ("compared", right_name))
    ladder, tallies = _ladder(result.findings, style), _tallies(result.findings, style)
    line = " %s     %s" % (ladder, tallies)
    if style.width and len(_ANSI_RE.sub("", line)) > style.width:   # a narrow terminal
        out += ["", " " + ladder, " " + tallies, ""]
    else:
        out += ["", line, ""]
    if not result.findings:
        out += [" " + style.paint("the two documents agree on everything compared", "ok"), ""]
    out += _tree(_shown(result.findings, full), style, full)
    for title, findings in (("the reference, checked against itself", self_left),
                            ("the compared document, checked against itself", self_right)):
        if findings:
            out += [" %s  %s" % (style.paint(title, "bold"), _tallies(findings, style, False)),
                    ""]
            out += _tree(_shown(findings, full), style, full)
    out += _footer(style, result.findings, full)
    return "\n".join(out).rstrip() + "\n"


def pair_text(design_name, spec_name, headline, findings, style=None, full=False):
    """The terminal report of a SWE.3 design held against its SWE.4 specification."""
    style = style or Style()
    out = _sides(style, ("design", design_name), ("specification", spec_name))
    out += ["", " " + headline, " " + _tallies(findings, style, False), ""]
    if not findings:
        out += [" " + style.paint("the design and the specification pair cleanly", "ok"), ""]
    out += _tree(_shown(findings, full), style, full, sides=("design", "specification"))
    out += _footer(style, findings, full)
    return "\n".join(out).rstrip() + "\n"


def self_text(name, doc_type, findings, style=None, full=False):
    """The terminal report of one document checked against its own rules."""
    style = style or Style()
    out = [" %s  %s, checked against itself" % (style.paint(os.path.basename(name), "bold"),
                                                doc_type),
           " " + _tallies(findings, style), ""]
    out += _tree(_shown(findings, full), style, full)
    out += _footer(style, findings, full)
    return "\n".join(out).rstrip() + "\n"


def to_json(result, left_name, right_name, self_left=None, self_right=None):
    payload = {
        "reference": left_name,
        "compared": right_name,
        "summary": {
            "findings": len(result.findings),
            "high": len([f for f in result.findings if f.severity == HIGH]),
            "medium": len([f for f in result.findings if f.severity == MEDIUM]),
            "low": len([f for f in result.findings if f.severity == LOW]),
            "info": len([f for f in result.findings if f.severity == INFO]),
        },
        "inventory": {
            kind: {
                "reference": result.left_total.get(kind, 0),
                "compared": result.right_total.get(kind, 0),
                "matched": result.matched.get(kind, 0),
                "score": round(result.score(kind), 4),
            }
            for kind in sorted(set(result.left_total) | set(result.right_total))
        },
        "self_checks": {
            "reference": [f.__dict__ for f in (self_left or [])],
            "compared": [f.__dict__ for f in (self_right or [])],
        },
        "findings": [f.__dict__ for f in result.findings],
    }
    return json.dumps(payload, indent=2, default=str) + "\n"
