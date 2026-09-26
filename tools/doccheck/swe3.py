"""SWE.3 Software Detailed Design: block stream in, entity tree out.

The structure, as `docs/spec/SWE3_WIKI.md` states it:

    1        Introduction
    N        <Component>
    N.1      Static Design            container + dependency diagrams, Component/Unit table
    N.1.K    <Unit>                   unit architecture diagram
    N.1.K.1  unit header              globals / typedef / enum / define table
    N.1.K.2  unit interface           the eight-column table
    N.1.K.M  <Unit>-<Function>        flowchart entry
    N.2      Dynamic Behaviour
    N.2.K    <Unit> - <Function> (<CallerUnit> - <CallerFunction>)
    N        Code Metrics, Coding Rule, Test Coverage
    Appendix A  Design Guideline

Two things in here are worth stating, because they decide whether a comparison is
useful or noise:

**The Interface ID is ours.** `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` is derived by this
tool, and `NN` is this tool's own numbering. Another author's document will not
share it, so rows are matched on Interface *Name* and the id is checked for
internal consistency instead (`id_integrity`).

**A unit appears twice** -- in the Component/Unit table and as a heading -- and so
does a function, as a flowchart heading and as an interface row. Those pairs are
recorded separately so a document can be checked against itself, with no second
document involved.
"""
from __future__ import annotations

import re

from . import cells
from .model import P1, P2, P4, Entity, Kind, Policy

DOC_TYPE = "SWE.3"

# Level-1 headings that are not a component. Matched on the leading words so a
# retitled "Code Metrics, Coding Rule and Test Coverage" still lands here.
_FIXED_SECTIONS = ("introduction", "code metrics", "design guideline", "appendix")

_IFACE_COLUMNS = {
    "interfaceId":   ["Interface ID", "IF ID", "ID"],
    "interfaceName": ["Interface Name", "Name"],
    "information":   ["Information", "Description", "Info"],
    "dataType":      ["Data Type", "Type of Data"],
    "dataRange":     ["Data Range", "Range"],
    "direction":     ["Direction(In/Out)", "Direction", "In/Out"],
    "sourceDest":    ["Source/Destination", "Source/Dest", "Source Destination"],
    "interfaceType": ["Interface Type", "Type"],
}

_UNIT_TABLE_COLUMNS = {
    "component":   ["Component"],
    "unit":        ["Unit"],
    "description": ["Description"],
    "note":        ["Note"],
}

# "<Unit> - <Function> (<CallerUnit> - <CallerFunction>)"
_INTERACTION_RE = re.compile(r"^(?P<unit>.+?)\s+-\s+(?P<func>.+?)\s*\(\s*(?P<cunit>.+?)\s+-\s+(?P<cfunc>.+?)\s*\)\s*$")

# The interface id, split so its parts can be checked against where it sits.
_IF_ID_RE = re.compile(r"^(?P<kind>P?IF)_(?P<rest>.+)_(?P<nn>\d+)$")


# --- how each field is compared ---------------------------------------------
#
# Every field names its level: a unit's sub-sections are an L3 fact, its row and
# image counts L4 facts, what a row says L5. Fields that only restate a count are
# marked `follows` so one fact is counted once.

POLICIES = {
    "interface": {
        "interfaceId":     Policy("ident", P4, "interface id (ours, not compared)"),
        "information":     Policy("text", P4, "Information"),
        "dataTypeParams":  Policy("seq", P1, "Data Type (parameters)"),
        "dataTypeReturn":  Policy("exact", P1, "Data Type (return)"),
        "dataRangeParams": Policy("seq", P2, "Data Range (parameters)"),
        "dataRangeReturn": Policy("exact", P2, "Data Range (return)"),
        "variableType":    Policy("exact", P1, "Data Type (global)"),
        "variableRange":   Policy("exact", P2, "Data Range (global)"),
        "direction":       Policy("enum", P1, "Direction"),
        "sourceDest":      Policy("names", P1, "Source/Destination"),
        "interfaceType":   Policy("enum", P1, "Interface Type"),
    },
    "unit": {
        "hasHeaderSection":    Policy("exact", P2, "unit header section", "L3"),
        "hasInterfaceSection": Policy("exact", P1, "unit interface section", "L3"),
        "hasHeaderTable":      Policy("exact", P2, "unit header table", "L4", "unit header table"),
        "hasInterfaceTable":   Policy("exact", P1, "unit interface table", "L4", "interface table"),
        "interfaceColumnSet":  Policy("set", P2, "interface table columns", "L4", "interface table"),
        "interfaceColumns":    Policy("seq", P4, "interface table column headings", "L4",
                                      "interface table"),
        "diagramCount":        Policy("exact", P2, "unit diagram images", "L4", "unit diagram"),
    },
    # A header row is identified by the SYMBOL it declares, so the declaration and its
    # value become compared FIELDS. Identifying it by the declaration text instead made the
    # row's own value part of its identity: `#define MAXN 256` against `#define MAXN 512`
    # read as one row missing and another appearing, and never as a changed value.
    "headerdef": {
        "declKind":    Policy("exact", P2, "kind"),
        "declaration": Policy("code", P2, "declaration"),
        "value":       Policy("exact", P2, "value"),
        # A struct, class or union's cell carries a sentence, not a value; a reworded
        # sentence is not a defect, which is what "text" means here.
        "description": Policy("text", P4, "description"),
    },
    "function": {
        "flowchartCount": Policy("exact", P2, "flowchart images", "L4", "flowcharts"),
        "risk":       Policy("exact", P2, "Risk"),
        "capacity":   Policy("exact", P2, "Capacity"),
        "inputName":  Policy("exact", P2, "Input Name"),
        "outputName": Policy("exact", P2, "Output Name"),
        "requirements": Policy("text", P4, "Requirements"),
    },
    "interaction": {
        "diagramCount":   Policy("exact", P2, "sequence diagram images", "L4"),
        "arrowCount":     Policy("exact", P2, "Behavior Description bullets", "L4"),
        "unit":           Policy("name", P1, "target unit"),
        "function":       Policy("name", P1, "target function"),
        "callerUnit":     Policy("name", P1, "calling unit"),
        "callerFunction": Policy("name", P1, "calling function"),
        "risk":           Policy("exact", P2, "Risk"),
        "capacity":       Policy("exact", P2, "Capacity"),
        "inputName":      Policy("exact", P2, "Input Name"),
        "outputName":     Policy("exact", P2, "Output Name"),
        "arrows":         Policy("seq", P2, "Behavior Description"),
    },
    "component": {
        "unitTableUnits": Policy("names", P2, "Component/Unit table rows", "L2"),
        "diagramCount":   Policy("exact", P2, "static design diagrams", "L4", "static design"),
    },
    "document": {},
}

# A field that only restates another field of the same entity: when both differ, the
# second is shown for its detail but counted under the first.
FOLLOWS = {
    ("unit", "hasHeaderTable"): "hasHeaderSection",
    ("unit", "hasInterfaceTable"): "hasInterfaceSection",
    ("unit", "interfaceColumns"): "interfaceColumnSet",
    ("interaction", "arrows"): "arrowCount",
}

# A field read from a table is compared only when both sides have the table: the
# columns of a table one side does not have are not "different", the table is missing.
FIELD_REQUIRES = {
    ("unit", "interfaceColumnSet"): "hasInterfaceTable",
    ("unit", "interfaceColumns"): "hasInterfaceTable",
}

# Which entities hang under which, and the level each one's presence is checked at.
KINDS = {
    "component":   Kind("L2", "components", "", P1, P1),
    "unit":        Kind("L2", "units", "", P1, P1),
    "interaction": Kind("L2", "dynamic behaviours", "Dynamic Behaviour"),
    "function":    Kind("L3", "function headings", "function sections"),
    "interface":   Kind("L4", "interface table rows", "interface table",
                        sub_field="interfaceType", requires="hasInterfaceTable"),
    "headerdef":   Kind("L4", "unit header table rows", "unit header table",
                        sub_field="declKind", requires="hasHeaderTable"),
}
CHILDREN = {
    "document": ("component",),
    "component": ("unit", "interaction"),
    "unit": ("function", "interface", "headerdef"),
}

# The kinds of heading the wiki fixes, in document order, and how loudly a missing
# kind is reported. L1 asks only whether each kind is there at all; how many there
# are is the business of the levels below.
HEADING_TYPES = (
    ("introduction", "Introduction", P2),
    ("introduction/purpose", "Introduction › Purpose", P4),
    ("introduction/scope", "Introduction › Scope", P4),
    ("introduction/terms", "Introduction › Terms, Abbreviations and Definitions", P4),
    ("component", "<Component>", P1),
    ("static", "<Component> › Static Design", P1),
    ("unit", "<Unit>", P1),
    ("unitheader", "<Unit> › unit header", P2),
    ("unitinterface", "<Unit> › unit interface", P1),
    ("function", "<Unit> › <Unit>-<Function>", P2),
    ("dynamic", "<Component> › Dynamic Behaviour", P2),
    ("interaction", "<Unit> - <Function> (<CallerUnit> - <CallerFunction>)", P2),
    ("metrics", "Code Metrics, Coding Rule, Test Coverage", P2),
    ("appendix", "Appendix A · Design Guideline", P2),
)

# Which child kind is counted at which rung of the ladder.
LEVELS = {kind: spec.level for kind, spec in KINDS.items()}

# What each level checks, as the report's summary table says it.
LEVEL_WHAT = {
    "L1": "every heading type is present",
    "L2": "components, units and dynamic behaviours (count and names)",
    "L3": "per unit: function headings (count and names), unit header and interface sections",
    "L4": "per table and diagram: rows (count and names), rows by kind, columns, images",
    "L5": "the cells of matched rows, declarations, function sections, behaviour arrows",
}

# Said once in every report, so nobody reads silence as agreement.
NOT_COMPARED = [
    "Interface IDs are not compared across two documents: each document numbers its own, so "
    "they are checked inside one document (see 'Each document on its own').",
    "Diagram and flowchart images are counted, not compared pixel by pixel.",
]


def _is_fixed_section(title: str) -> bool:
    return fixed_section_key(title) is not None


def fixed_section_key(title: str):
    """The canonical name of a fixed section, or None when it is not one.

    `Introduction` and `Introduction and Purpose` are the same section under two
    titles. Keying them both to `Introduction` means a retitled section is
    recognised rather than reported as one missing and one added.
    """
    t = (title or "").casefold()
    for prefix in _FIXED_SECTIONS:
        if t.startswith(prefix):
            return prefix
    return None


# The columns that make a table *the* interface table, whatever it heads them.
_IFACE_REQUIRED = ("interfaceName", "direction", "interfaceType")


def _is_interface_table(cols) -> bool:
    """Whether a resolved column map identifies an eight-column interface table."""
    if not all(name in cols for name in _IFACE_REQUIRED):
        return "interfaceId" in cols and "interfaceName" in cols and len(cols) >= 5
    return True


def _iface_row(row, cols, index):
    """One interface table row -> an `interface` entity, cells parsed by grammar."""
    def cell(fieldname):
        i = cols.get(fieldname)
        return row[i] if i is not None and i < len(row) else None

    name_cell = cell("interfaceName")
    name = name_cell.text if name_cell else ""
    ent = Entity(kind="interface", name=name, index=index)

    id_cell = cell("interfaceId")
    ent.fields["interfaceId"] = id_cell.text if id_cell else ""

    info_cell = cell("information")
    ent.fields["information"] = info_cell.text if info_cell else ""

    it = cell("interfaceType")
    ent.fields["interfaceType"] = it.text if it else ""

    dt = cell("dataType")
    dr = cell("dataRange")

    # The same two columns carry different things on the two kinds of row
    # (`docx_exporter.py:942`): a global's Data Type is its declared type, a
    # function's is its parameter list plus a `return:` line. Reading a global's
    # type as a one-parameter list would compare it against the wrong thing.
    if (ent.fields["interfaceType"] or "").casefold().startswith("global"):
        ent.fields["variableType"] = dt.text if dt else ""
        ent.fields["variableRange"] = dr.text if dr else ""
    else:
        params, ret = cells.typed_list(dt.texts if dt else [])
        rparams, rret = cells.typed_list(dr.texts if dr else [])
        # A function with no parameters is written "VOID" / "NA" (`docx_exporter.py:947`).
        # `typed_list` drops the lone VOID; the matching NA can only be recognised
        # by reading the two cells together, because a *real* parameter may also
        # have the range NA -- a pointer, for one.
        if not params and len(rparams) == 1 and rparams[0].casefold() in ("na", "n/a", "-"):
            rparams = []
        ent.fields["dataTypeParams"] = params
        ent.fields["dataTypeReturn"] = ret or ""
        ent.fields["dataRangeParams"] = rparams
        ent.fields["dataRangeReturn"] = rret or ""

    d = cell("direction")
    ent.fields["direction"] = d.text if d else ""

    sd = cell("sourceDest")
    ent.fields["sourceDest"] = cells.name_set(sd.text if sd else "")
    return ent


# The kinds whose second cell is a sentence ("Structure for ...", "Union for ..."), not a
# value -- `views/unit_headers.py` gives all three a one-line description.
_RECORD_KINDS = ("struct", "class", "union")


def header_row(text, info="", index=0):
    """One row of a unit header table, named by the symbol it declares.

    The one place a header row is built -- the extractor uses it, and so do the tests,
    so what they check is what a document gets.
    """
    kind, sym, norm = cells.declaration(text)
    # Fall back to the raw text as the name: a row nobody can parse must
    # still be a row, or the comparison loses it silently.
    ent = Entity(kind="headerdef", name=sym or text, index=index)
    ent.fields["declKind"] = kind or "unparsed"
    ent.fields["declaration"] = norm or text
    # A value and a description are different fields because they deserve different
    # severities. A typedef gets either, depending on whether it stands for an enum
    # (values) or for a record (a sentence).
    if kind in _RECORD_KINDS or (kind == "typedef" and "=" not in info):
        ent.fields["description"] = info
    else:
        ent.fields["value"] = info
    return ent


def _behaviour_fields(ent, rows):
    """Fill the Requirements / Risk / Capacity / Input Name / Output Name rows."""
    kv = cells.key_value_rows(rows)
    req = cells.find_label(kv, "Requirements")
    if req is not None:
        ent.fields["arrows"] = cells.bullets(req.texts, drop_header="Behavior Description")
        ent.fields["requirements"] = req.text
        ent.images.extend(req.images)
    for fieldname, *labels in (
        ("risk", "Risk"),
        ("capacity", "Capacity", "Capacity(Density)"),
        ("inputName", "Input Name"),
        ("outputName", "Output Name"),
    ):
        c = cells.find_label(kv, *labels)
        if c is not None:
            ent.fields[fieldname] = c.text
    return ent


# Fixed sections -> their heading type.
_FIXED_TYPE = {"introduction": "introduction", "code metrics": "metrics",
               "design guideline": "appendix", "appendix": "appendix"}
_INTRO_SUBS = (("purpose", "introduction/purpose"), ("scope", "introduction/scope"),
               ("terms", "introduction/terms"))


def other_heading(level, title):
    """The heading type of a heading the wiki does not name: its level and its title."""
    return "other: H%d %s" % (level, (title or "").strip())


def extract(blocks) -> Entity:
    """A SWE.3 block stream as an entity tree."""
    doc = Entity(kind="document", name=DOC_TYPE, key=DOC_TYPE)
    headings = {}                        # heading type -> how many
    cover = []
    component = None
    fixed = None                         # the fixed level-1 section we are in, if any
    section = None                       # "static" | "dynamic" | None
    unit = None
    func = None                          # the entity a stray table belongs to
    counters = {}

    def _count(kind):
        counters[kind] = counters.get(kind, 0) + 1
        return counters[kind] - 1

    def _seen(heading_type):
        headings[heading_type] = headings.get(heading_type, 0) + 1

    for b in blocks:
        if b.kind == "heading":
            if b.level == 1:
                unit = func = section = None
                fixed = fixed_section_key(b.text)
                if fixed:
                    component = None
                    _seen(_FIXED_TYPE[fixed])
                    doc.children.append(Entity(kind="section", name=b.text, key=fixed,
                                               number=b.number, index=_count("section")))
                else:
                    _seen("component")
                    component = Entity(kind="component", name=b.text, number=b.number,
                                       index=_count("component"))
                    component.fields["level"] = b.level
                    doc.children.append(component)

            elif b.level == 2:
                unit = func = None
                t = b.text.casefold()
                if component is None:
                    section = None
                    if fixed == "introduction":
                        _seen(next((key for word, key in _INTRO_SUBS if t.startswith(word)),
                                   other_heading(2, b.text)))
                    else:
                        _seen(other_heading(2, b.text))
                elif t.startswith("static"):
                    section = "static"
                    component.fields["hasStatic"] = True
                    _seen("static")
                elif t.startswith("dynamic"):
                    section = "dynamic"
                    component.fields["hasDynamic"] = True
                    _seen("dynamic")
                else:
                    section = None
                    _seen(other_heading(2, b.text))

            elif b.level == 3 and component is not None and section == "static":
                func = None
                _seen("unit")
                unit = Entity(kind="unit", name=b.text, number=b.number, index=_count("unit"))
                unit.images.extend(b.images)
                component.children.append(unit)

            elif b.level == 3 and component is not None and section == "dynamic":
                _seen("interaction")
                unit = None
                ent = Entity(kind="interaction", name=b.text, number=b.number,
                             index=_count("interaction"))
                m = _INTERACTION_RE.match(b.text)
                if m:
                    ent.fields["unit"] = m.group("unit").strip()
                    ent.fields["function"] = m.group("func").strip()
                    ent.fields["callerUnit"] = m.group("cunit").strip()
                    ent.fields["callerFunction"] = m.group("cfunc").strip()
                ent.fields["heading"] = b.text
                ent.images.extend(b.images)
                component.children.append(ent)
                func = ent

            elif b.level == 4 and unit is not None:
                t = b.text.casefold()
                if t.startswith("unit header"):
                    _seen("unitheader")
                    func = None
                    unit.fields["hasHeaderSection"] = True
                elif t.startswith("unit interface"):
                    _seen("unitinterface")
                    func = None
                    unit.fields["hasInterfaceSection"] = True
                else:
                    _seen("function")
                    name = cells.function_of(b.text, unit.name)
                    func = Entity(kind="function", name=name, number=b.number,
                                  index=_count("function"))
                    func.fields["qualifiedName"] = b.text
                    func.fields["heading"] = b.text
                    func.images.extend(b.images)
                    unit.children.append(func)
            else:
                _seen(other_heading(b.level, b.text))

        elif b.kind == "para":
            target = func or unit or component
            if target is not None and b.images:
                target.images.extend(b.images)
            elif component is None and not doc.children and b.text:
                cover.append(b.text)

        elif b.kind == "table":
            header = b.header
            probe = " ".join(header).casefold()
            cols = cells.resolve_columns(header, _IFACE_COLUMNS)

            # Recognised by what the columns *are*, not by our own header text.
            # A client's table heads the same eight columns differently and puts
            # them in another order; matching on the literal "Interface ID" would
            # not recognise it at all, and the whole table would go unread.
            if unit is not None and _is_interface_table(cols):
                unit.fields["hasInterfaceTable"] = True
                unit.fields["interfaceColumns"] = list(header)
                unit.fields["interfaceColumnSet"] = sorted(cols)
                for i, row in enumerate(b.rows[1:]):
                    if not any(c.text for c in row):
                        continue
                    unit.children.append(_iface_row(row, cols, i))

            elif "global variables" in probe and unit is not None:
                unit.fields["hasHeaderTable"] = True
                for i, row in enumerate(b.rows[1:]):
                    if not row or not row[0].text:
                        continue
                    info = row[1].text if len(row) > 1 else ""
                    unit.children.append(header_row(row[0].text, info, i))

            elif component is not None and "component" in probe and "unit" in probe:
                cols = cells.resolve_columns(header, _UNIT_TABLE_COLUMNS)
                ui = cols.get("unit")
                names = []
                for row in b.rows[1:]:
                    if ui is not None and ui < len(row) and row[ui].text:
                        names.append(row[ui].text)
                component.fields["unitTableUnits"] = names

            elif func is not None and len(header) == 2:
                _behaviour_fields(func, b.rows)

    if cover:
        doc.fields["cover"] = cover
    _not_components(doc, headings)
    doc.fields["headingTypes"] = headings
    _finalise(doc)
    return doc


def _not_components(doc, headings):
    """A level-1 heading nothing hangs under -- no Static Design, no Dynamic Behaviour,
    no unit -- is a section of its own ("Revision History"), not a component. Reading
    it as one would report a whole component missing for a page of prose."""
    for c in list(doc.of_kind("component")):
        if c.fields.get("hasStatic") or c.fields.get("hasDynamic") or c.children \
                or c.fields.get("unitTableUnits"):
            continue
        doc.children.remove(c)
        headings["component"] -= 1
        if not headings["component"]:
            del headings["component"]
        key = other_heading(1, c.name)
        headings[key] = headings.get(key, 0) + 1
        doc.children.append(Entity(kind="section", name=c.name, number=c.number,
                                   key=key, index=c.index))
    for c in doc.of_kind("component"):
        for flag in ("level", "hasStatic", "hasDynamic"):
            c.fields.pop(flag, None)


def _finalise(doc):
    """Derived counts the comparator reads, filled once the tree is complete."""
    for component in doc.of_kind("component"):
        component.fields.setdefault("unitTableUnits", [])
        component.fields["diagramCount"] = len(component.images)
        for unit in component.of_kind("unit"):
            for flag in ("hasHeaderSection", "hasInterfaceSection", "hasHeaderTable",
                         "hasInterfaceTable"):
                unit.fields.setdefault(flag, False)
            unit.fields["diagramCount"] = len(unit.images)
            for func in unit.of_kind("function"):
                func.fields["flowchartCount"] = len(func.images)
        for ia in component.of_kind("interaction"):
            ia.fields["diagramCount"] = len(ia.images)
            ia.fields["arrowCount"] = len(ia.fields.get("arrows") or [])


def heading_types(doc):
    """{heading type: how many}, as `extract` records it -- or, for a tree built some
    other way (a test, another reader), derived from the tree itself."""
    got = doc.fields.get("headingTypes")
    if got is not None:
        return got
    out = {}

    def seen(key, n=1):
        if n:
            out[key] = out.get(key, 0) + n
    for section in doc.of_kind("section"):
        fixed = fixed_section_key(section.name)
        seen(_FIXED_TYPE.get(fixed, other_heading(1, section.name)) if fixed
             else other_heading(1, section.name))
    for component in doc.of_kind("component"):
        seen("component")
        seen("static")
        units = component.of_kind("unit")
        seen("unit", len(units))
        seen("unitheader", sum(1 for u in units if u.fields.get("hasHeaderSection")
                               or u.fields.get("hasHeaderTable")))
        seen("unitinterface", sum(1 for u in units if u.fields.get("hasInterfaceSection")
                                  or u.fields.get("hasInterfaceTable")))
        seen("function", sum(len(u.of_kind("function")) for u in units))
        interactions = component.of_kind("interaction")
        seen("dynamic", 1 if interactions else 0)
        seen("interaction", len(interactions))
    return out


# --- checks a document can fail on its own ----------------------------------

# What a single document is checked for at each level, on its own.
SELF_LEVEL_WHAT = {
    "L1": "(no single-document check at this level)",
    "L2": "the Component/Unit table lists exactly the unit sections",
    "L3": "every function row has a flowchart entry; no two headings read the same",
    "L4": "every flowchart entry has a row; functions are numbered before globals",
    "L5": "Interface IDs are well formed, gapless and name their unit",
}

# Each self-check's level, priority and the view it is about.
SELF_CHECKS = {
    "id-malformed":          ("L5", P1, "interface table"),
    "id-private-published":  ("L5", P1, "interface table"),
    "id-gap":                ("L5", P1, "interface table"),
    "id-wrong-unit":         ("L5", P2, "interface table"),
    "id-order":              ("L4", P2, "interface table"),
    "unit-table-only":       ("L2", P1, ""),
    "unit-heading-only":     ("L2", P1, ""),
    "function-not-in-interface-table": ("L4", P2, "interface table"),
    "row-without-heading":   ("L3", P2, "function sections"),
    "duplicate-heading":     ("L3", P2, "function sections"),   # overloads are legal C++
    # The headings name their unit: the same rules the SWE.4 document is held to.
    "heading-unit-mismatch": ("L3", P2, "function sections"),
    "interaction-heading-unreadable": ("L2", P2, "Dynamic Behaviour"),
    "interaction-unit-unknown": ("L2", P2, "Dynamic Behaviour"),
    "interaction-function-unknown": ("L2", P2, "Dynamic Behaviour"),
}


def _id_numbers(ifaces):
    """The trailing numbers of a unit's ids, in document order, for the report."""
    out = []
    for iface in ifaces:
        m = _IF_ID_RE.match((iface.fields.get("interfaceId") or "").strip())
        out.append(m.group("nn") if m else "?")
    return out


def id_integrity(doc):
    """Findings that need only one document: the Interface ID against its place.

    The wiki fixes the id as `IF_<LAYER>_<GROUP>_<UNIT>_<NN>`, numbered within the
    unit, functions first then globals, with no gaps. All of that is checkable
    without a second document -- and the id is the one column a client document
    will never agree with, so this is where its value is.
    """
    out = []
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            ifaces = unit.of_kind("interface")
            seen_global = False
            expected = 0
            reported_gap = False
            for iface in ifaces:
                raw = iface.fields.get("interfaceId", "")
                where = "%s / %s / %s" % (component.name, unit.name, iface.name or "?")
                m = _IF_ID_RE.match(raw.strip())
                if not m:
                    out.append(("id-malformed", where,
                                "interface id %r does not read IF_<LAYER>_<GROUP>_<UNIT>_<NN>" % raw))
                    continue
                if m.group("kind") == "PIF":
                    out.append(("id-private-published", where,
                                "%s is a private id; the wiki says PIF_ never appears in the document" % raw))
                expected += 1
                nn = int(m.group("nn"))
                if nn != expected and not reported_gap:
                    # Only the FIRST break per unit. Once the numbering is wrong,
                    # every row after it is suspect for the same reason, and
                    # reporting each one buries the one edit that caused them.
                    out.append(("id-gap", where,
                                "interface id numbering reads %02d where %02d was due; the "
                                "unit's ids are %s" % (nn, expected,
                                                       ", ".join(_id_numbers(ifaces)))))
                    reported_gap = True
                expected = nn
                # unit part of the id should end with the unit's own letters
                unit_probe = re.sub(r"[^A-Za-z0-9]", "", unit.name).upper()
                rest = m.group("rest").upper()
                if unit_probe and not rest.endswith(re.sub(r"[^A-Z0-9]", "", unit_probe)):
                    out.append(("id-wrong-unit", where,
                                "interface id %r does not end with the unit %r" % (raw, unit.name)))
                itype = (iface.fields.get("interfaceType") or "").casefold()
                if itype.startswith("global"):
                    seen_global = True
                elif seen_global:
                    out.append(("id-order", where,
                                "a Function row follows a Global Variable row; the wiki numbers "
                                "functions first, then globals"))
    return out


def self_consistency(doc):
    """Findings from the two places the same fact is written in one document.

    A unit is named in the Component/Unit table and again as a heading; a function
    is named by a flowchart heading and again as an interface row. When those
    disagree the document is wrong about itself, and no client document is needed
    to say so.
    """
    from .model import normalise_key
    out = []
    for component in doc.of_kind("component"):
        heading_units = {normalise_key(u.name): u.name for u in component.of_kind("unit")}
        # An interaction heading names a unit and a function of THIS component: the one the
        # outside call enters. Both must be there, or the diagram describes something the
        # static design does not.
        units_by_key = {normalise_key(u.name): u for u in component.of_kind("unit")}
        for ia in component.of_kind("interaction"):
            where = "%s / %s" % (component.name, ia.name)
            if not ia.fields.get("unit"):
                out.append(("interaction-heading-unreadable", where,
                            "the heading does not read "
                            "'<Unit> - <Function> (<CallerUnit> - <CallerFunction>)'"))
                continue
            target = units_by_key.get(normalise_key(ia.fields["unit"]))
            if target is None:
                out.append(("interaction-unit-unknown", where,
                            "the heading names the unit %r, which has no section in %s"
                            % (ia.fields["unit"], component.name)))
                continue
            known = {normalise_key(x.name) for x in target.children
                     if x.kind in ("function", "interface")}
            if normalise_key(ia.fields.get("function", "")) not in known:
                out.append(("interaction-function-unknown", where,
                            "the heading names the function %r, which unit %r has no heading "
                            "or row for" % (ia.fields.get("function"), target.name)))
        table_units = {normalise_key(n): n for n in component.fields.get("unitTableUnits", [])}
        for key, name in sorted(table_units.items()):
            if key not in heading_units:
                out.append(("unit-table-only", component.name,
                            "%r is in the Component/Unit table but has no unit section" % name))
        for key, name in sorted(heading_units.items()):
            if key not in table_units:
                out.append(("unit-heading-only", component.name,
                            "%r has a unit section but is missing from the Component/Unit table" % name))

        for unit in component.of_kind("unit"):
            where = "%s / %s" % (component.name, unit.name)
            iface_fns = {normalise_key(i.name): i.name for i in unit.of_kind("interface")
                         if (i.fields.get("interfaceType") or "").casefold().startswith("func")}
            headings = {}
            for func in unit.of_kind("function"):
                headings.setdefault(normalise_key(func.name), []).append(func)
                text = func.fields.get("heading") or ""
                if text and not cells.starts_with_unit(text, unit.name):
                    out.append(("heading-unit-mismatch", "%s / %s" % (where, func.name),
                                "the heading %r does not start with its unit %r"
                                % (text, unit.name)))
            for func in unit.of_kind("function"):
                if normalise_key(func.name) not in iface_fns:
                    out.append(("function-not-in-interface-table",
                                "%s / %s" % (where, func.name),
                                "%r has a flowchart entry but no row in the unit interface table"
                                % func.name))
            # The other way round: a public function is a row AND a heading. Only checked
            # when the unit has function headings at all -- a document written without the
            # flowchart sections is a different document, not one missing every heading.
            if unit.of_kind("function") and unit.fields.get("hasInterfaceTable"):
                for key, name in sorted(iface_fns.items()):
                    if key not in headings:
                        out.append(("row-without-heading", "%s / %s" % (where, name),
                                    "%r has a row in the unit interface table but no flowchart "
                                    "entry" % name))
            for key, funcs in sorted(headings.items()):
                if len(funcs) > 1:
                    out.append(("duplicate-heading", "%s / %s" % (where, funcs[0].name),
                                "%d function headings read %r; two functions a reader cannot "
                                "tell apart" % (len(funcs), funcs[0].fields.get("heading")
                                                or funcs[0].name)))
    return out
