"""A DOCX read as a stream of blocks, with structure kept instead of flattened.

`tools/dump_docx.py` turns a document into text so two of them can be `diff`ed.
That is the right shape for reading, and the wrong shape for comparing: it joins
a cell's paragraphs with ` // ` and escapes `|`, so a cell that legitimately holds
` // ` and a cell holding two paragraphs become the same string.

Here the same body walk keeps what the text form throws away -- a cell is a list
of paragraphs plus the images inside it, and a heading keeps its number apart from
its title. Nothing is interpreted: that is the profile's job (`swe3`, `swe4`).

Order is document order, read off the body the way Word stores it, so section
structure holds.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from docx import Document
    from docx.oxml.ns import qn
except ImportError:                      # same message the exporters would give
    raise SystemExit("python-docx is required: pip install python-docx")

EMU_PER_INCH = 914400

# "2.1.1 ArmGuarded" -> ("2.1.1", "ArmGuarded"); "Appendix A. Design Guideline"
# -> ("A", "Design Guideline"). A heading with no number keeps number "".
_NUM_RE = re.compile(r"^(?:Appendix\s+)?([0-9][0-9.]*|[A-Z])[.)]?\s+(.*)$")


@dataclass
class Cell:
    """One table cell: its paragraphs, and the images drawn inside it."""
    texts: list = field(default_factory=list)
    images: list = field(default_factory=list)

    @property
    def text(self) -> str:
        """The cell as a single line, for fields that are genuinely one value."""
        return " ".join(t for t in self.texts if t).strip()

    def __bool__(self) -> bool:
        return bool(self.texts or self.images)


@dataclass
class Block:
    """One body element. `kind` is 'heading', 'para' or 'table'."""
    kind: str
    level: int = 0                       # heading depth, 0 for body text
    number: str = ""                     # "2.1.1" / "A" / "" when unnumbered
    text: str = ""                       # heading title, or paragraph text
    images: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    @property
    def header(self) -> list:
        """First row as plain strings -- a table's column names."""
        return [c.text for c in self.rows[0]] if self.rows else []


def _image_sha(el, part) -> Optional[str]:
    """sha1[:8] of the image a w:drawing / w:pict embeds, or None if unresolvable."""
    for blip in el.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if rid and rid in part.related_parts:
            try:
                return hashlib.sha1(part.related_parts[rid].blob).hexdigest()[:8]
            except Exception:            # external / unresolvable relationship
                return None
        return None
    return None


def _para(p, part):
    """One paragraph -> (its text lines, the image shas in it).

    A `w:br` ends a line, so a cell written as several visual lines in one
    paragraph still reads as several values.
    """
    lines = []
    images = []
    cur = []
    for el in p._p.iter():
        tag = el.tag
        if tag == qn("w:t"):
            cur.append(el.text or "")
        elif tag == qn("w:tab"):
            cur.append(" ")
        elif tag == qn("w:br"):
            lines.append("".join(cur))
            cur = []
        elif tag in (qn("w:drawing"), qn("w:pict")):
            sha = _image_sha(el, part)
            if sha:
                images.append(sha)
    lines.append("".join(cur))
    # Word splits one visible line across many runs, sometimes with stray spaces
    # between them; collapse so a re-export that only re-splits runs compares equal.
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    return [ln for ln in lines if ln], images


def _heading_level(p) -> int:
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


def split_number(text: str):
    """('2.1.1 ArmGuarded') -> ('2.1.1', 'ArmGuarded').

    The number is a position, never an identity -- inserting one unit renumbers
    everything below it -- so it is kept only to quote in a report.
    """
    m = _NUM_RE.match(text.strip())
    if not m:
        return "", text.strip()
    return m.group(1).rstrip("."), m.group(2).strip()


def _cell(tc_cell, part) -> Cell:
    """A cell's paragraphs and images; a nested table is flattened into rows of text."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    out = Cell()
    for child in tc_cell._tc.iterchildren():
        if child.tag == qn("w:p"):
            texts, images = _para(Paragraph(child, tc_cell), part)
            out.texts.extend(texts)
            out.images.extend(images)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, tc_cell).rows:
                inner = [_cell(c, part) for c in row.cells]
                line = " / ".join(c.text for c in inner if c.text)
                if line:
                    out.texts.append(line)
                for c in inner:
                    out.images.extend(c.images)
    return out


def _rows(table, part):
    """Table rows, de-duplicating the cells a horizontal merge repeats."""
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for c in row.cells:
            # python-docx yields a merged cell once per grid column it spans;
            # identity of the underlying tc element is what tells them apart.
            key = id(c._tc)
            if key in seen:
                continue
            seen.add(key)
            cells.append(_cell(c, part))
        rows.append(cells)
    return rows


def read(path: str):
    """The whole document as a block stream, in document order."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    part, body = doc.part, doc.element.body
    out = []

    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            level = _heading_level(p)
            texts, images = _para(p, part)
            if not texts and not images:
                continue
            if level:
                number, title = split_number(texts[0] if texts else "")
                out.append(Block(kind="heading", level=level, number=number,
                                 text=title, images=images))
                for extra in texts[1:]:
                    out.append(Block(kind="para", text=extra))
            elif texts:
                for i, t in enumerate(texts):
                    out.append(Block(kind="para", text=t,
                                     images=images if i == 0 else []))
            else:
                out.append(Block(kind="para", text="", images=images))
        elif child.tag == qn("w:tbl"):
            out.append(Block(kind="table", rows=_rows(Table(child, doc), part)))
    return out
