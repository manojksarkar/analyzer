"""Why a difference is there, when one of our own documented rules explains it.

A list of differences is a diff. A list of differences where each one carries the
rule that would produce it is a worklist -- the reader can tell at a glance which
lines are ours to fix and which are the tool behaving as agreed.

Every attribution here is evidenced by something in the two documents. Nothing is
guessed from the source code, which the tool never sees, and an attribution is a
*candidate* reason: it lowers a finding's severity to INFO only where the rule
fully accounts for it, and otherwise just annotates.

The rules are the ones written down in `docs/spec/SWE3_WIKI.md`.
"""
from __future__ import annotations

from .model import INFO, LOW, is_placeholder, normalise_key

# Section anchors, so a reader can go and check the claim.
WIKI = "docs/spec/SWE3_WIKI.md"


def _index(doc):
    """Lookups the attributions need, built once per document."""
    units, functions, interfaces = {}, {}, {}
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            units[normalise_key(unit.name)] = unit
            for func in unit.of_kind("function"):
                functions.setdefault(normalise_key(unit.name), set()).add(normalise_key(func.name))
            for iface in unit.of_kind("interface"):
                interfaces.setdefault(normalise_key(unit.name), {})[normalise_key(iface.name)] = iface
    return {"units": units, "functions": functions, "interfaces": interfaces}


def _leaf(path):
    return path.rsplit(" / ", 1)[-1] if path else ""


def _unit_of(path):
    """'Cross / Dispatch / divide' -> 'Dispatch'."""
    parts = [p for p in (path or "").split(" / ") if p]
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


def annotate(result, left, right):
    """Attach a rule to every finding one explains. Returns the count annotated."""
    li, ri = _index(left), _index(right)
    annotated = 0

    for finding in result.findings:
        rule = None
        demote = False
        leaf = normalise_key(_leaf(finding.path))
        unit_key = normalise_key(_unit_of(finding.path))

        if finding.kind == "extra" and "unit" in finding.summary:
            unit = ri["units"].get(leaf)
            if unit is not None and not unit.of_kind("interface") and not unit.of_kind("function"):
                rule = ("their section has no interface table and no functions, which is what a "
                        "header-only unit looks like; we give a section only to a unit that has a "
                        "source file (%s, 'Which units get a section')" % WIKI)

        elif finding.kind == "missing" and "interface" in finding.summary:
            # A row we do not publish, whose name is nonetheless a heading there.
            if leaf in ri["functions"].get(unit_key, set()):
                rule = ("the name is a heading in their document but not a row, so the two "
                        "documents disagree about public vs private (%s, 'Public vs. private')" % WIKI)
            else:
                rule = ("we leave private items out of the table entirely -- no row, no arrow, "
                        "no heading (%s, 'Interface ID')" % WIKI)

        elif finding.kind == "missing" and "function" in finding.summary:
            if leaf in ri["interfaces"].get(unit_key, {}):
                rule = ("the function has an interface row but no flowchart entry, which is what "
                        "`hidden` in the settings does (%s, 'Hidden functions')" % WIKI)

        elif finding.kind == "differs" and finding.field == "sourceDest":
            a = {normalise_key(x) for x in (finding.left or [])}
            b = {normalise_key(x) for x in (finding.right or [])}
            if a and a < b:
                rule = ("Source/Destination lists the units that *call* this function and nothing "
                        "else; names only they have may be callees (%s, 'Column 7')" % WIKI)
            elif not a and b:
                rule = ("an empty Source/Destination means nothing in the documented scope calls "
                        "it; code outside the group is not counted (%s, 'Which units get a "
                        "section')" % WIKI)

        elif finding.kind == "differs" and finding.field in ("dataRangeParams", "dataRangeReturn",
                                                             "variableRange"):
            if is_placeholder(finding.left) or is_placeholder(finding.right):
                rule = ("a range is looked up by type name and is NA when nothing in the data "
                        "dictionary answers; a supplied CSV (--data-dictionary) beats every other "
                        "source (%s, 'Data Range')" % WIKI)

        elif finding.kind == "differs" and finding.field == "direction":
            iface = li["interfaces"].get(unit_key, {}).get(leaf)
            if iface is not None and (iface.fields.get("interfaceType") or "").casefold().startswith("global"):
                rule = ("a global variable is always In/Out (%s, 'Column 6')" % WIKI)

        elif finding.kind == "differs" and finding.field in ("risk", "capacity"):
            rule = ("Risk is fixed at Medium and Capacity at Common; neither is worked out from "
                    "the code (%s, 'Fixed and placeholder values')" % WIKI)
            demote = True

        elif finding.kind == "differs" and finding.field == "interfaceId":
            rule = ("the interface id is derived by this tool and its number is ours; it is not "
                    "expected to agree across documents (%s, 'Interface ID')" % WIKI)
            demote = True

        if rule:
            finding.rule = rule
            annotated += 1
            if demote:
                finding.severity = INFO

    result.findings.sort(key=lambda f: f.sort_key())
    return annotated
