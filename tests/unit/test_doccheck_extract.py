"""The SWE.3 extractor against the pipeline's own data.

`interface_tables.json` is written by the view that the DOCX exporter then renders,
and it sits next to every generated document. That makes it a free oracle: if the
extractor reads a document back into the same rows the pipeline put into it, the
extractor is right -- and no eyeballing of a Word file was involved.

The test models what `engine/docx_exporter.py` renders, not what the model holds,
because the document is what a client sends back:

    parameters   "type name", joined with "; ", or "VOID" when there are none
    return       a `return:` paragraph, "VOID" when the return type is void
    range        "NA" for a void return
    global rows  Data Type is the declared type, not a parameter list

Skips when no generated documents are on disk, so a clean checkout still passes.
"""
import glob
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

pytest.importorskip("docx", reason="python-docx is needed to read a .docx")

from doccheck import blocks, swe3                      # noqa: E402
from doccheck.model import normalise_key               # noqa: E402

pytestmark = pytest.mark.unit

_SEARCH = [
    os.path.join(_ROOT, "output_review", "all-groups", "*"),
    os.path.join(_ROOT, "output", "*"),
    os.path.join(_ROOT, "workspaces", "*", "versions", "*", "output", "*"),
]


def _pairs():
    """(label, docx path, interface_tables.json path) for every generated group."""
    out, seen = [], set()
    for pattern in _SEARCH:
        for d in sorted(glob.glob(pattern)):
            oracle = os.path.join(d, "interface_tables.json")
            docx = sorted(glob.glob(os.path.join(d, "software_detailed_design_*.docx")))
            if not docx or not os.path.isfile(oracle):
                continue
            label = os.path.basename(d)
            if label in seen:
                continue
            seen.add(label)
            out.append((label, docx[0], oracle))
    return out


PAIRS = _pairs()
if not PAIRS:
    pytest.skip("no generated SWE.3 documents on disk", allow_module_level=True)


def _rendered(entry):
    """What the exporter puts in the Data Type / Data Range cells for one entry."""
    if "variableType" in entry:
        return {
            "variableType": (entry.get("variableType") or "").strip() or "-",
            "variableRange": (entry.get("range") or "").strip() or "NA",
        }
    params = entry.get("parameters") or []
    types, ranges = [], []
    for p in params:
        t = (p.get("type") or "").strip()
        n = (p.get("name") or "").strip()
        types.append((t + " " + n).strip() if n else t)
        ranges.append((p.get("range") or "").strip())
    ret = (entry.get("returnType") or "").strip()
    is_void = ret.casefold() == "void"
    return {
        "dataTypeParams": types,
        "dataRangeParams": ranges,
        "dataTypeReturn": ("VOID" if is_void else ret) if ret else "",
        "dataRangeReturn": ("NA" if is_void else ((entry.get("returnRange") or "").strip() or "NA")) if ret else "",
    }


def _extracted(docx_path):
    """{unit key: {interface key: entity}} read back out of the document."""
    doc = swe3.extract(blocks.read(docx_path))
    out = {}
    for component in doc.of_kind("component"):
        for unit in component.of_kind("unit"):
            bucket = out.setdefault(normalise_key(unit.name), {})
            for iface in unit.of_kind("interface"):
                bucket[normalise_key(iface.name)] = iface
    return out


def _oracle(path):
    """{unit key: {interface key: entry}} as the pipeline wrote it."""
    data = json.load(open(path, encoding="utf-8"))
    out = {}
    for key, block in data.items():
        if key == "unitNames" or not isinstance(block, dict):
            continue
        bucket = out.setdefault(normalise_key(block.get("name", "")), {})
        for entry in block.get("entries", []):
            bucket[normalise_key(entry.get("interfaceName", ""))] = entry
    return out


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=[p[0] for p in PAIRS])
def test_every_model_row_is_read_back_out_of_the_document(label, docx_path, oracle_path):
    got, want = _extracted(docx_path), _oracle(oracle_path)
    problems = []

    for unit_key, entries in sorted(want.items()):
        if not entries:
            continue
        if unit_key not in got:
            problems.append("unit %s has rows in the model but no section in the document" % unit_key)
            continue
        for iface_key, entry in sorted(entries.items()):
            row = got[unit_key].get(iface_key)
            if row is None:
                problems.append("%s/%s is in the model but not in the document" % (unit_key, iface_key))
                continue
            expect = dict(_rendered(entry))
            expect["interfaceId"] = entry.get("interfaceId", "")
            expect["direction"] = entry.get("direction", "")
            expect["interfaceType"] = entry.get("type", "")
            sd = entry.get("sourceDest") or ""
            expect["sourceDest"] = sorted({s.strip() for s in sd.split(",")
                                           if s.strip() and s.strip() != "-"})
            for fieldname, wanted in sorted(expect.items()):
                actual = row.fields.get(fieldname)
                if actual != wanted:
                    problems.append("%s/%s %s: document=%r model=%r"
                                    % (unit_key, iface_key, fieldname, actual, wanted))

    assert not problems, "%s: %d mismatch(es)\n  %s" % (label, len(problems), "\n  ".join(problems[:25]))


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=[p[0] for p in PAIRS])
def test_the_document_invents_no_rows_the_model_does_not_have(label, docx_path, oracle_path):
    got, want = _extracted(docx_path), _oracle(oracle_path)
    extra = []
    for unit_key, rows in sorted(got.items()):
        known = want.get(unit_key, {})
        for iface_key in sorted(rows):
            if iface_key not in known:
                extra.append("%s/%s" % (unit_key, iface_key))
    assert not extra, "%s: rows in the document with no model entry: %s" % (label, extra)


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=[p[0] for p in PAIRS])
def test_units_and_components_survive_the_round_trip(label, docx_path, oracle_path):
    doc = swe3.extract(blocks.read(docx_path))
    components = doc.of_kind("component")
    assert components, "%s: no component sections were found" % label
    # Every component must carry its Component/Unit table, and every unit in that
    # table must have a section -- this is the check that needs no second document.
    assert not swe3.self_consistency(doc), (
        "%s: the document disagrees with itself: %s" % (label, swe3.self_consistency(doc)))


@pytest.mark.parametrize("label,docx_path,oracle_path", PAIRS, ids=[p[0] for p in PAIRS])
def test_interface_ids_are_well_formed_and_gapless(label, docx_path, oracle_path):
    doc = swe3.extract(blocks.read(docx_path))
    findings = swe3.id_integrity(doc)
    assert not findings, "%s: %s" % (label, findings[:10])
