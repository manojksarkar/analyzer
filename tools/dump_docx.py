"""Dump a generated .docx to reviewable plain text.

A DOCX is a zip: you cannot diff two of them, and you cannot see what a run
actually produced without opening Word. This flattens one into a stable text
form -- headings as `#`, tables as markdown pipe rows, and every image as
`[image w=<width> sha=<sha1[:8]>]` -- so two documents (before/after a change,
DB backing vs file backing, SWE.3 vs SWE.4) can be diffed with `diff`.

Images are reduced to a hash on purpose: the byte content is what matters for
"did the diagram change", and the hash makes that a one-line answer instead of
a binary blob. Same image reused across the document keeps the same hash.

Order is document order -- paragraphs and tables are read off the body in the
order Word stores them, not paragraphs-then-tables, so section structure holds.

    python tools/dump_docx.py output/My-Sample/software_detailed_design_My-Sample.docx
    python tools/dump_docx.py <a.docx> -o a.md && python tools/dump_docx.py <b.docx> -o b.md && diff a.md b.md
"""
import argparse
import hashlib
import os
import re
import sys

try:
    from docx import Document
    from docx.oxml.ns import qn
except ImportError:                      # same message the exporters would give
    print("python-docx is required: pip install python-docx", file=sys.stderr)
    raise SystemExit(2)

EMU_PER_INCH = 914400
PAGE_BREAK = "[page break]"


def _image_token(drawing, part):
    """`[image w=6.00in sha=1234abcd]` for one w:drawing / w:pict element."""
    width = ""
    for ext in drawing.iter(qn("wp:extent")):
        try:
            width = " w=%.2fin" % (int(ext.get("cx")) / EMU_PER_INCH)
        except (TypeError, ValueError):
            pass
        break
    sha = "?"
    for blip in drawing.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if rid and rid in part.related_parts:
            try:
                sha = hashlib.sha1(part.related_parts[rid].blob).hexdigest()[:8]
            except Exception:            # external / unresolvable relationship
                sha = "?"
        break
    return "[image%s sha=%s]" % (width, sha)


def _para_lines(p, part):
    """One paragraph -> its text lines (a page break inside it starts a new line)."""
    lines, cur = [], []
    for el in p._p.iter():
        tag = el.tag
        if tag == qn("w:t"):
            cur.append(el.text or "")
        elif tag == qn("w:tab"):
            cur.append("\t")
        elif tag == qn("w:br"):
            # a page break becomes its own line; a soft break just ends this one
            page = el.get(qn("w:type")) == "page"
            lines.append("".join(cur))
            cur = [PAGE_BREAK] if page else []
        elif tag in (qn("w:drawing"), qn("w:pict")):
            cur.append(("" if not cur or "".join(cur).endswith(" ") else " ")
                       + _image_token(el, part))
    lines.append("".join(cur))
    # Word splits one visible line across many runs, sometimes with stray spaces
    # between them; collapse so a re-export that only re-splits runs still diffs clean.
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    return [ln for ln in lines if ln]


def _heading_level(p):
    """Heading depth from the paragraph style, or 0 for body text."""
    try:
        name = (p.style.name or "")
    except Exception:
        return 0
    if name.startswith("Heading "):
        try:
            return int(name.split()[1])
        except (IndexError, ValueError):
            return 0
    return 0


def _cell_text(cell, part):
    """Cell content as one line -- paragraphs joined by ` // `, nested tables flattened."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    parts = []
    for child in cell._tc.iterchildren():
        if child.tag == qn("w:p"):
            parts.extend(_para_lines(Paragraph(child, cell), part))
        elif child.tag == qn("w:tbl"):
            for row in Table(child, cell).rows:
                cells = [_cell_text(c, part) for c in row.cells]
                parts.append(" / ".join(c for c in cells if c))
    return " // ".join(p for p in parts if p).replace("|", r"\|")


def _table_lines(table, part):
    """Markdown pipe table -- first row is the header, as the exporters build them."""
    lines = []
    for i, row in enumerate(table.rows):
        cells = [_cell_text(c, part) for c in row.cells]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + "---|" * len(cells))
    return lines


def dump(path):
    """The whole document as a list of output lines."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    part, body = doc.part, doc.element.body
    out = []

    def blank_before():
        if out and out[-1] != "":
            out.append("")

    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            pbb = child.find(qn("w:pPr"))
            if pbb is not None and pbb.find(qn("w:pageBreakBefore")) is not None:
                out.append(PAGE_BREAK)
            level = _heading_level(p)
            lines = _para_lines(p, part)
            if not lines:
                continue
            if level:
                blank_before()
                lines[0] = "#" * level + " " + lines[0]
            out.extend(lines)
        elif child.tag == qn("w:tbl"):
            blank_before()
            out.extend(_table_lines(Table(child, doc), part))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docx", help="path to the .docx to dump")
    ap.add_argument("-o", "--out", help="write here instead of stdout")
    a = ap.parse_args()

    if not os.path.isfile(a.docx):
        print("no such file: %s" % a.docx, file=sys.stderr)
        return 2
    text = "\n".join(dump(a.docx)) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s (%d lines)" % (a.out, text.count("\n")))
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
