"""Check UT-automation JSON files against the UT templates.

The template IS the schema (docs/spec/ut_templates/, how to read them in its README).
From it the check learns every key path, the JSON types each path may hold, which keys
are always present, and where keys are free-form -- a dict whose keys are all
placeholders ("<SECTION_NAME>": {...}) takes any key. A new sample means a new
template, not new code; the only hand-kept rule is ENUM_PATHS.

One rule set, two uses:
  - a received JSON: does a real file match our understanding of the format?
  - our JSON: does what ArtiFex emits match the target format?

IT cases are skipped: IT is out of scope here and will come from SWE.2.

    python tools/check_ut_json.py <file.json> [more.json ...]    # template picked per file
    python tools/check_ut_json.py <file.json> --template hierarchy
    python tools/check_ut_json.py <file.json> --template path/to/other.template.json

Exit code: 0 clean, 1 an ERROR in any file (or a file that is not JSON), 2 usage.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "docs", "spec", "ut_templates")
TEMPLATES = {"testcase": "testcase.template.json",
             "hierarchy": "hierarchy.template.json"}

# `<Anything>` inside a key or a string is template placeholder syntax.
TOKEN = re.compile(r"<[^<>\s][^<>]*>")

# Paths whose template values are a closed set, not examples. Any other literal in the
# template (SectionID "ABC1", EnvironmentId "PQR1") is an example and is not enforced.
ENUM_PATHS = {
    "format_version",
    "cases[].level",
    "cases[].stubs[].mode",
    "environment.probepoint[].position",
    "cases[].inputs[].escape_hatch.language",
    "cases[].inputs[].escape_hatch.kind",
}

OUT_OF_SCOPE_LEVELS = {"IT"}  # integration tests come from SWE.2, not SWE.4

SEVERITY_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}


def jtype(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


class Node:
    """Everything the template shows about one schema path, merged over its occurrences."""

    def __init__(self):
        self.types = set()      # json types seen; a placeholder-keyed dict is "map"
        self.keys = {}          # object: key -> Node
        self.key_seen = {}      # object: key -> occurrences that had it
        self.obj_seen = 0       # object occurrences, the denominator for key_seen
        self.map_value = None   # map: Node shared by every value
        self.item = None        # array: Node shared by every element
        self.strings = set()    # string values seen


def learn(node, v):
    t = jtype(v)
    if t == "object":
        if v and all(TOKEN.search(k) for k in v):
            node.types.add("map")
            node.map_value = node.map_value or Node()
            for val in v.values():
                learn(node.map_value, val)
        else:
            node.types.add("object")
            node.obj_seen += 1
            for k, val in v.items():
                node.keys.setdefault(k, Node())
                node.key_seen[k] = node.key_seen.get(k, 0) + 1
                learn(node.keys[k], val)
    elif t == "array":
        node.types.add("array")
        for val in v:
            node.item = node.item or Node()
            learn(node.item, val)
    else:
        node.types.add(t)
        if t == "string":
            node.strings.add(v)


def template_tokens(v, out):
    """Every `<...>` token in the template -- the placeholder vocabulary."""
    if isinstance(v, dict):
        for k, val in v.items():
            out.update(TOKEN.findall(k))
            template_tokens(val, out)
    elif isinstance(v, list):
        for val in v:
            template_tokens(val, out)
    elif isinstance(v, str):
        out.update(TOKEN.findall(v))
    return out


class Findings:
    """Findings grouped by (severity, kind, schema path, detail): one row, a count, a first location."""

    def __init__(self):
        self.groups = {}

    def add(self, severity, kind, path, detail, where):
        key = (severity, kind, path, detail)
        if key in self.groups:
            self.groups[key][0] += 1
        else:
            self.groups[key] = [1, where or "(root)"]

    def rows(self):
        """(severity, kind, path, detail, count, first location), worst first."""
        return sorted(((s, k, p, d, n, w) for (s, k, p, d), (n, w) in self.groups.items()),
                      key=lambda r: (SEVERITY_ORDER[r[0]], r[2], r[1]))

    def count(self, severity):
        return sum(1 for r in self.rows() if r[0] == severity)


def _join(base, key):
    return f"{base}.{key}" if base else key


def check(node, v, spath, where, out, tokens, allow_placeholders):
    t = jtype(v)
    allowed = node.types
    if not (t in allowed
            or (t == "object" and "map" in allowed)
            or (t == "integer" and "number" in allowed)):
        out.add("ERROR", "type", spath or "(root)",
                f"{t}; template has {', '.join(sorted(allowed))}", where)
        return

    if t == "object":
        if "map" in allowed and not node.keys:
            for k, val in v.items():
                check(node.map_value, val, _join(spath, "*"), _join(where, k),
                      out, tokens, allow_placeholders)
            return
        for k, val in v.items():
            if k in node.keys:
                check(node.keys[k], val, _join(spath, k), _join(where, k),
                      out, tokens, allow_placeholders)
            else:
                out.add("ERROR", "unknown-key", _join(spath, k), "not in the template", where)
        for k in node.keys:
            if k not in v:
                have, total = node.key_seen[k], node.obj_seen
                if have == total:
                    out.add("ERROR", "missing", _join(spath, k),
                            f"in every template occurrence ({have}/{total})", where)
                else:
                    out.add("INFO", "missing-optional", _join(spath, k),
                            f"in {have}/{total} template occurrences", where)
    elif t == "array":
        if node.item is not None:
            for i, val in enumerate(v):
                check(node.item, val, spath + "[]", f"{where}[{i}]",
                      out, tokens, allow_placeholders)
    elif t == "string":
        if spath in ENUM_PATHS and v not in node.strings:
            seen = ", ".join(sorted(repr(s) for s in node.strings))
            out.add("WARN", "enum", spath, f"{v!r} not in the template's set ({seen})", where)
        if v == "" and "" not in node.strings:
            out.add("INFO", "empty", spath, "empty string; the template fills it", where)
        if not allow_placeholders and any(tok in v for tok in tokens):
            out.add("INFO", "placeholder", spath, "a template placeholder was left in", where)


def ut_only(doc):
    """`doc` with IT cases removed, and how many there were.

    The template keeps its IT example -- that is part of the format -- but IT is out
    of scope here, so it neither shapes the case rules nor gets checked.
    """
    if not (isinstance(doc, dict) and isinstance(doc.get("cases"), list)):
        return doc, 0
    kept = [c for c in doc["cases"]
            if not (isinstance(c, dict) and c.get("level") in OUT_OF_SCOPE_LEVELS)]
    return dict(doc, cases=kept), len(doc["cases"]) - len(kept)


def pick_template(payload):
    """Which template a file follows, from its top-level keys; None when neither fits."""
    if isinstance(payload, dict) and "cases" in payload:
        return "testcase"
    if isinstance(payload, dict) and ("LayerMapping" in payload or "Macros" in payload):
        return "hierarchy"
    return None


def run(payload, template, allow_placeholders=False):
    """Check one parsed file against one parsed template. Returns Findings."""
    schema = Node()
    learn(schema, ut_only(template)[0])
    out = Findings()
    payload, skipped = ut_only(payload)
    for _ in range(skipped):
        out.add("INFO", "skipped", "cases[]", "IT case, out of scope (comes from SWE.2)", "cases")
    check(schema, payload, "", "", out, template_tokens(template, set()), allow_placeholders)
    return out


def render(out, file_label, template_label):
    lines = [f"{file_label}  vs  {template_label}",
             f"{out.count('ERROR')} error(s) | {out.count('WARN')} warning(s) | "
             f"{out.count('INFO')} info   (one row per schema path; xN = occurrences)", ""]
    rows = out.rows()
    if not rows:
        lines.append("matches the template")
    width = max((len(r[2]) for r in rows), default=0)
    for severity, kind, path, detail, n, where in rows:
        lines.append(f"{severity:<5}  {kind:<16}  {path:<{width}}  {detail}"
                     + (f"  x{n}" if n > 1 else "") + f"   e.g. {where}")
    return "\n".join(lines)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def template_path(name):
    """A template name ("testcase" / "hierarchy") or a file path -> the file; None if neither."""
    if os.path.isfile(name):
        return name
    if name in TEMPLATES:
        return os.path.join(TEMPLATE_DIR, TEMPLATES[name])
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", metavar="file")
    ap.add_argument("--template", help="testcase | hierarchy | a template file path "
                                       "(default: picked per file from its content)")
    ap.add_argument("--allow-placeholders", action="store_true",
                    help="do not report <...> placeholders (when checking a template itself)")
    args = ap.parse_args(argv)

    if args.template and template_path(args.template) is None:
        print(f"unknown template {args.template!r}: use testcase, hierarchy or a file path",
              file=sys.stderr)
        return 2

    failed = False
    for i, path in enumerate(args.files):
        if i:
            print()
        try:
            payload = load(path)
        except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
            print(f"{path}  cannot be read as JSON: {exc}")
            failed = True
            continue
        name = args.template or pick_template(payload)
        if name is None:
            print(f"{path}  neither a test-case nor a hierarchy file; pass --template",
                  file=sys.stderr)
            return 2
        tpath = template_path(name)
        out = run(payload, load(tpath), args.allow_placeholders)
        print(render(out, path, os.path.basename(tpath)))
        failed = failed or bool(out.count("ERROR"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
