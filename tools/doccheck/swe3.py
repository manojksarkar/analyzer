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
from .model import HIGH, INFO, LOW, MEDIUM, Entity, Policy

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

POLICIES = {
    "interface": {
        "interfaceId":     Policy("ident", INFO, "interface id (ours, not compared)"),
        "information":     Policy("text", INFO, "Information"),
        "dataTypeParams":  Policy("seq", HIGH, "Data Type (parameters)"),
        "dataTypeReturn":  Policy("exact", HIGH, "Data Type (return)"),
        "dataRangeParams": Policy("seq", MEDIUM, "Data Range (parameters)"),
        "dataRangeReturn": Policy("exact", MEDIUM, "Data Range (return)"),
        "variableType":    Policy("exact", HIGH, "Data Type (global)"),
        "variableRange":   Policy("exact", MEDIUM, "Data Range (global)"),
        "direction":       Policy("enum", HIGH, "Direction"),
        "sourceDest":      Policy("names", HIGH, "Source/Destination"),
        "interfaceType":   Policy("enum", HIGH, "Interface Type"),
    },
    "unit": {
        "hasHeaderTable":   Policy("exact", LOW, "unit header table present"),
        "hasInterfaceTable": Policy("exact", MEDIUM, "unit interface table present"),
        "diagramCount":     Policy("exact", LOW, "unit diagrams"),
    },
    "headerdef": {
        "information": Policy("text", INFO, "information"),
    },
    "function": {
        "risk":       Policy("exact", LOW, "Risk"),
        "capacity":   Policy("exact", LOW, "Capacity"),
        "inputName":  Policy("exact", MEDIUM, "Input Name"),
        "outputName": Policy("exact", MEDIUM, "Output Name"),
        "flowchartCount": Policy("exact", MEDIUM, "flowcharts"),
        "requirements": Policy("text", INFO, "Requirements"),
    },
    "interaction": {
        "unit":           Policy("name", HIGH, "target unit"),
        "function":       Policy("name", HIGH, "target function"),
        "callerUnit":     Policy("name", HIGH, "calling unit"),
        "callerFunction": Policy("name", HIGH, "calling function"),
        "risk":           Policy("exact", LOW, "Risk"),
        "capacity":       Policy("exact", LOW, "Capacity"),
        "inputName":      Policy("exact", MEDIUM, "Input Name"),
        "outputName":     Policy("exact", MEDIUM, "Output Name"),
        "arrows":         Policy("seq", MEDIUM, "Behavior Description bullets"),
        "diagramCount":   Policy("exact", MEDIUM, "sequence diagrams"),
    },
    "component": {
        "unitTableUnits": Policy("names", MEDIUM, "Component/Unit table"),
        "diagramCount":   Policy("exact", LOW, "static design diagrams"),
    },
    "section": {},
    "document": {},
}

# Which child kind is counted at which rung of the ladder.
LEVELS = {
    "section": "L0",
    "component": "L1",
    "unit": "L1",
    "interface": "L2",
    "headerdef": "L2",
    "function": "L2",
    "interaction": "L4",
}


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


def extract(blocks) -> Entity:
    """A SWE.3 block stream as an entity tree."""
    doc = Entity(kind="document", name=DOC_TYPE, key=DOC_TYPE)
    cover = []
    component = None
    section = None                       # "static" | "dynamic" | None
    unit = None
    func = None                          # the entity a stray table belongs to
    subsection = None                    # "header" | "interface" | "function"
    counters = {}

    def _count(kind):
        counters[kind] = counters.get(kind, 0) + 1
        return counters[kind] - 1

    for b in blocks:
        if b.kind == "heading":
            if b.level == 1:
                unit = func = section = None
                subsection = None
                fixed = fixed_section_key(b.text)
                if fixed:
                    component = None
                    doc.children.append(Entity(kind="section", name=b.text, key=fixed,
                                               number=b.number, index=_count("section")))
                else:
                    component = Entity(kind="component", name=b.text, number=b.number,
                                       index=_count("component"))
                    doc.children.append(component)

            elif b.level == 2:
                unit = func = None
                subsection = None
                t = b.text.casefold()
                if component is None:
                    section = None
                elif t.startswith("static"):
                    section = "static"
                elif t.startswith("dynamic"):
                    section = "dynamic"
                else:
                    section = None

            elif b.level == 3 and component is not None:
                func = None
                subsection = None
                if section == "static":
                    unit = Entity(kind="unit", name=b.text, number=b.number,
                                  index=_count("unit"))
                    unit.images.extend(b.images)
                    component.children.append(unit)
                elif section == "dynamic":
                    unit = None
                    ent = Entity(kind="interaction", name=b.text, number=b.number,
                                 index=_count("interaction"))
                    m = _INTERACTION_RE.match(b.text)
                    if m:
                        ent.fields["unit"] = m.group("unit").strip()
                        ent.fields["function"] = m.group("func").strip()
                        ent.fields["callerUnit"] = m.group("cunit").strip()
                        ent.fields["callerFunction"] = m.group("cfunc").strip()
                    ent.images.extend(b.images)
                    component.children.append(ent)
                    func = ent

            elif b.level == 4 and unit is not None:
                t = b.text.casefold()
                if t.startswith("unit header"):
                    subsection, func = "header", None
                    unit.fields["hasHeaderTable"] = False
                elif t.startswith("unit interface"):
                    subsection, func = "interface", None
                    unit.fields["hasInterfaceTable"] = False
                else:
                    subsection = "function"
                    name = cells.function_of(b.text, unit.name)
                    func = Entity(kind="function", name=name, number=b.number,
                                  index=_count("function"))
                    func.fields["qualifiedName"] = b.text
                    func.images.extend(b.images)
                    unit.children.append(func)

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
                for i, row in enumerate(b.rows[1:]):
                    if not any(c.text for c in row):
                        continue
                    unit.children.append(_iface_row(row, cols, i))

            elif "global variables" in probe and unit is not None:
                unit.fields["hasHeaderTable"] = True
                for i, row in enumerate(b.rows[1:]):
                    if not row or not row[0].text:
                        continue
                    ent = Entity(kind="headerdef", name=row[0].text, index=i)
                    ent.fields["information"] = row[1].text if len(row) > 1 else ""
                    unit.children.append(ent)

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
    _finalise(doc)
    return doc


def _finalise(doc):
    """Derived counts the comparator reads, filled once the tree is complete."""
    for component in doc.of_kind("component"):
        component.fields.setdefault("unitTableUnits", [])
        component.fields["diagramCount"] = len(component.images)
        for unit in component.of_kind("unit"):
            unit.fields.setdefault("hasHeaderTable", False)
            unit.fields.setdefault("hasInterfaceTable", False)
            unit.fields["diagramCount"] = len(unit.images)
            for func in unit.of_kind("function"):
                func.fields["flowchartCount"] = len(func.images)
        for ia in component.of_kind("interaction"):
            ia.fields["diagramCount"] = len(ia.images)


# --- checks a document can fail on its own ----------------------------------

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
            iface_fns = {normalise_key(i.name) for i in unit.of_kind("interface")
                         if (i.fields.get("interfaceType") or "").casefold().startswith("func")}
            for func in unit.of_kind("function"):
                if normalise_key(func.name) not in iface_fns:
                    out.append(("function-not-in-interface-table",
                                "%s / %s" % (component.name, unit.name),
                                "%r has a flowchart entry but no row in the unit interface table"
                                % func.name))
    return out
