"""Why a difference is there, when one of our own documented rules explains it.

A list of differences is a diff. A list of differences where each one carries the
rule that would produce it is a worklist -- the reader can tell at a glance which
lines are ours to fix and which are the tool behaving as agreed.

Every attribution here is evidenced by something in the two documents. Nothing is
guessed from the source code, which the tool never sees. A rule comes in two
strengths:

- **explained** -- the rule fully accounts for the difference. The finding drops
  to P3: listed with the rule, never counted as a defect.
- **possible reason** -- the rule would produce this, but the documents cannot
  prove it did. The finding keeps its priority and carries the rule as a lead.

The rules are the ones written down in `docs/spec/SWE3_WIKI.md` and
`docs/spec/SWE4_WIKI.md`, and each profile has its own: a SWE.3 rule about
header-only units says nothing about a SWE.4 document.
"""
from __future__ import annotations

import re

from .model import P3, canonical_enum, is_placeholder, normalise_key, normalise_text

# Section anchors, so a reader can go and check the claim.
WIKI = "docs/spec/SWE3_WIKI.md"
WIKI4 = "docs/spec/SWE4_WIKI.md"

EXPLAINED, POSSIBLE = True, False

# The engine's word split for SWE3-UI-05 row 1 (`model_deriver._WORD_RE`, `_name_words`):
# camelCase and snake_case into words, so `coreSetResult` holds `set` and `Setup` does not.
# Copied, not imported -- this tool reads documents, not the engine -- and kept equal by
# tests/unit/test_doccheck_compare.py.
_WORD_RE = re.compile(r'[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+')


def _name_words(name):
    return {w.lower() for w in _WORD_RE.findall(name or "")}


def _direction_from_the_documents(rows):
    """(direction, why) that SWE3-UI-05 gives a function from what its rows show -- the name
    (row 1) and the return type (row 2) -- or (None, "") when it turns on what the code
    writes (rows 3-4), which no document shows."""
    name = next((r.name for r in rows if r.name), "")
    short = name.split("(")[0].strip().rsplit("::", 1)[-1]
    words = _name_words(short)
    if "set" in words:
        return "In", "its name holds the word Set"
    if "get" in words:
        return "Out", "its name holds the word Get"
    returns = {(r.fields.get("dataTypeReturn") or "").strip() for r in rows} - {""}
    if len(returns) != 1:                    # not shown, or the two documents disagree on it
        return None, ""
    ret = returns.pop()
    if ret.casefold() == "void" or is_placeholder(ret):
        return None, ""
    return "Out", "it returns a value (%s)" % ret


def _function_direction(f, rows):
    """The direction rule for one function row, as far as the documents can take it."""
    said = [canonical_enum("direction", v) for v in (f.left, f.right)]
    if "In/Out" in said:
        return ("In/Out is a global variable's Direction; a function is In or Out "
                "(%s, SWE3-UI-05)" % WIKI)
    want, why = _direction_from_the_documents(rows)
    if want is not None:
        wrong = [s for s in said if s != want]
        return ("SWE3-UI-05 gives %s here, before anything the code writes: %s; the document "
                "that says %s breaks it (%s, SWE3-UI-05)" % (want, why, " / ".join(wrong), WIKI))
    # A void function with neither word: what decides it is in the code. Since 2026-11-24
    # (review SWE3-025) a method that writes its own object's member variables is In, so a
    # document made before then says Out for it.
    return ("it returns nothing and its name has neither Set nor Get, so its Direction turns "
            "on what the code writes: a global, or a member variable of its own object -- by "
            "itself, by a function it calls or through a local pointer -- makes it In; nothing "
            "written, Out. A method that writes its own object's member variables is In since "
            "2026-11-24; a document made before then says Out (%s, SWE3-UI-05)" % WIKI)


def _index(doc):
    """Lookups the attributions need, built once per document."""
    units, functions, interfaces, headerdefs = {}, {}, {}, {}
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            units[normalise_key(unit.name)] = unit
            for func in unit.of_kind("function"):
                functions.setdefault(normalise_key(unit.name), set()).add(normalise_key(func.name))
            for iface in unit.of_kind("interface"):
                interfaces.setdefault(normalise_key(unit.name), {})[normalise_key(iface.name)] = iface
            for hd in unit.of_kind("headerdef"):
                headerdefs.setdefault(normalise_key(unit.name), {})[normalise_key(hd.name)] = hd
    return {"units": units, "functions": functions, "interfaces": interfaces,
            "headerdefs": headerdefs}


def _listed_in_another_unit(index, unit_key, leaf):
    """The name of the first OTHER unit (sorted) whose header table lists `leaf`, or ''."""
    for other in sorted(index["headerdefs"]):
        if other != unit_key and leaf in index["headerdefs"][other]:
            unit = index["units"].get(other)
            return unit.name if unit is not None else other
    return ""


# --- SWE.3 ------------------------------------------------------------------------

def _swe3(f, li, ri):
    """(rule, explained) for one SWE.3 finding, or None."""
    leaf = normalise_key(f.item)
    unit_key = normalise_key(f.unit)

    if f.kind == "extra" and f.entity == "unit":
        unit = ri["units"].get(leaf)
        if unit is not None and not unit.of_kind("interface") and not unit.of_kind("function"):
            return ("their section has no interface table and no functions, which is what a "
                    "header-only unit looks like; we give a section only to a unit that has a "
                    "source file (%s, SWE3-DOC-03)" % WIKI), POSSIBLE

    if f.kind == "missing" and f.entity == "interface":
        gone = li["interfaces"].get(unit_key, {}).get(leaf)
        # A GLOBAL row we do not publish: since S3-7 a global needs a reader or writer in
        # another unit, as a function needs a caller there. A document written to the old
        # rule (the marking alone) lists every non-private global.
        if gone is not None and (gone.fields.get("interfaceType") or "").casefold().startswith("global"):
            return ("a global gets a row only when a function in another unit reads or "
                    "writes it; one its own unit alone uses is left out (%s, "
                    "SWE3-UI-01)" % WIKI), POSSIBLE
        if leaf in ri["functions"].get(unit_key, set()):
            return ("the name is a heading in their document but not a row, so the two "
                    "documents disagree about public vs private (%s, SWE3-UI-01)"
                    % WIKI), POSSIBLE
        return ("we leave private items out of the table entirely -- no row, no arrow, "
                "no heading (%s, SWE3-UI-01)" % WIKI), POSSIBLE

    if f.kind == "missing" and f.entity == "function":
        return ("a private or hidden function gets no flowchart entry and no interface row "
                "(%s, SWE3-UI-01, SWE3-DOC-06)" % WIKI), POSSIBLE

    if f.kind == "differs" and f.field == "sourceDest":
        a = {normalise_key(x) for x in (f.left or [])}
        b = {normalise_key(x) for x in (f.right or [])}
        if a and a < b:
            return ("Source/Destination lists the units that *call* this function and nothing "
                    "else; names only they have may be callees (%s, SWE3-UI-06)" % WIKI), POSSIBLE
        if not a and b:
            return ("an empty Source/Destination means nothing in the documented scope calls "
                    "it; code outside the group is not counted (%s, "
                    "SWE3-UI-06)" % WIKI), POSSIBLE

    if f.kind == "differs" and f.field in ("dataRangeParams", "dataRangeReturn", "variableRange"):
        if is_placeholder(f.left) or is_placeholder(f.right):
            return ("a range is looked up by type name and is NA when nothing in the data "
                    "dictionary answers; a supplied CSV (--data-dictionary) beats every other "
                    "source (%s, SWE3-UI-04)" % WIKI), POSSIBLE

    if f.kind == "differs" and f.field == "direction":
        rows = [r for r in (li["interfaces"].get(unit_key, {}).get(leaf),
                            ri["interfaces"].get(unit_key, {}).get(leaf)) if r is not None]
        if any(canonical_enum("interfaceType", r.fields.get("interfaceType")) == "Global Variable"
               for r in rows):
            return "a global variable is always In/Out (%s, SWE3-UI-05)" % WIKI, POSSIBLE
        return _function_direction(f, rows), POSSIBLE

    if f.kind in ("missing", "extra") and f.entity == "headerdef":
        # RV-4: an orphan header's symbols are listed ONCE, in the header's owner unit.
        # A row missing from this unit on one side and present in ANOTHER unit of the
        # same side is that move, not a loss -- the evidence is in the document itself.
        where = _listed_in_another_unit(ri if f.kind == "missing" else li, unit_key, leaf)
        if where:
            side = "we list" if f.kind == "missing" else "they list"
            return ("a symbol from a header with no source file of its own is listed once, in "
                    "one owner unit; %s it under %s (%s, SWE3-UH-04)"
                    % (side, where, WIKI)), EXPLAINED
        if f.kind == "extra":
            # A header row only WE have. Since 2026-09-23 this table is not filtered by
            # visibility, so a document written to the older rule is missing exactly the
            # rows whose declaration says private -- a marking, or a class-scoped static.
            ent = ri["headerdefs"].get(unit_key, {}).get(leaf)
            decl = ((ent.fields.get("declaration") if ent is not None else "") or "").upper()
            if "PRIVATE" in decl or "PROTECTED" in decl or "STATIC" in decl or "::" in decl:
                return ("the unit header table lists what a unit declares and uses, not what it "
                        "publishes, so a private or file-local declaration belongs in it; a "
                        "document written to the older rule leaves these out (%s, "
                        "SWE3-UH-01)" % WIKI), EXPLAINED
        # A header row THEY have and we do not carries no rule. It used to: a `union` or a
        # `using` alias never reached our data dictionary. Both are recorded since 147c4cd
        # (review answer Q16), and the rule would now explain away a row that is missing.

    if f.kind == "differs" and f.field in ("risk", "capacity"):
        return ("Risk is fixed at Medium and Capacity at Common; neither is worked out from "
                "the code (%s, SWE3-FX-01)" % WIKI), EXPLAINED

    if f.kind == "differs" and f.field == "interfaceId":
        return ("the interface id is derived by this tool and its number is ours; it is not "
                "expected to agree across documents (%s, SWE3-UI-02)" % WIKI), EXPLAINED

    if f.kind == "extra" and f.field == "otherHeading":
        return ("a heading the wiki does not name; we do not write this section (%s, "
                "SWE3-DOC-02)" % WIKI), POSSIBLE
    return None


# --- SWE.4 ------------------------------------------------------------------------

# The Table B values the wiki fixes, and the ones the configuration sets.
_FIXED4 = {
    "generationMethod": ("Test Case Generation Method", "Analysis of Requirements"),
    "aliasTestId": ("Alias Test ID", "-"),
    "risk": ("Risk", "-"),
    "testMethod": ("Test Method", "-"),
    "linkedWorkItems": ("Linked Work Items", "-"),
}
_CONFIGURED4 = {
    "priority": "Priority (default Medium)",
    "testEnvironment": "Test Environment (default Emulator)",
    "evalEquipment": "Eval. Equipment Name",
    "platform": "Test Platform",
}


def _swe4(f, li, ri):
    """(rule, explained) for one SWE.4 finding, or None."""
    if f.kind == "differs" and f.field in _FIXED4:
        label, fixed = _FIXED4[f.field]
        sides = [str(v or "").strip().strip("`").casefold() for v in (f.left, f.right)]
        if fixed.casefold() in sides:
            return ("%s is fixed at %r; it is not worked out from the code (%s, 'Table B')"
                    % (label, fixed, WIKI4)), EXPLAINED

    if f.kind == "differs" and f.field in _CONFIGURED4:
        return ("%s comes from the configuration, not from the code (%s, 'Table B')"
                % (_CONFIGURED4[f.field], WIKI4)), EXPLAINED

    if f.kind == "differs" and f.field == "expected":
        # Only an `updated` entry one side has: that is what a write the code makes decides.
        left = {normalise_text(x) for x in (f.left or [])}
        right = {normalise_text(x) for x in (f.right or [])}
        if any("successfully updated" in x for x in left ^ right):
            return ("Expected Results has one entry per out-parameter and per global the "
                    "function writes. Since 2026-11-24 a global written through a local pointer "
                    "or reference to it (`p = &g_tab[i]; p->a = 1;`) counts as written "
                    "(SWE3-UI-05 row 4), so a document made before then lacks that entry "
                    "(%s, 'Expected Results')" % WIKI4), POSSIBLE

    if f.kind == "missing" and f.entity == "testcase":
        return ("a public function defined in a header gets no spec of its own; it is "
                "covered through its own unit's callers (%s, 'Who gets a spec')" % WIKI4), POSSIBLE

    if f.kind in ("missing", "extra") and f.entity == "unit":
        return ("a unit gets a section only when one of its functions gets a spec; a unit "
                "whose public functions are all defined in a header has none (%s, 'Who gets "
                "a spec')" % WIKI4), POSSIBLE

    if f.kind in ("missing", "extra") and f.entity == "interaction":
        return ("an interaction spec exists exactly where the SWE.3 document draws a "
                "behaviour diagram, and only when both are switched on in the settings (%s, "
                "'Dynamic Behaviour test specs')" % WIKI4), POSSIBLE
    return None


_BY_TYPE = {"SWE.3": _swe3, "SWE.4": _swe4}


def annotate(result, left, right, profile=None):
    """Attach a rule to every finding one explains. Returns the count annotated."""
    doc_type = getattr(profile, "DOC_TYPE", "") or result.doc_type or "SWE.3"
    rule_of = _BY_TYPE.get(doc_type)
    if rule_of is None:
        return 0
    li, ri = _index(left), _index(right)
    annotated = 0
    for finding in result.findings:
        if finding.follows:
            continue
        got = rule_of(finding, li, ri)
        if not got:
            continue
        rule, explained = got
        finding.rule = rule
        annotated += 1
        if explained:
            finding.was = finding.priority
            finding.priority = P3
            finding.explained = True
    result.findings.sort(key=lambda f: f.sort_key())
    return annotated
