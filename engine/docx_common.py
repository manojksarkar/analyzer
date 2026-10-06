"""DOCX helpers shared by the document exporters.

Extracted from docx_exporter.py when SWE.4 gained its own exporter: the cover
page, table of contents, model/abbreviation loading and the cell/paragraph leaf
helpers are identical across documents, so they live here and each exporter
imports them. docx_exporter.py imports them under its original private names,
which is why the SWE.3 document is unchanged by the extraction.
"""
import json
import os

from core.paths import paths as _paths

_p = _paths()
PROJECT_ROOT = _p.project_root
MODEL_DIR = _p.model_dir


#: How long `save_docx` waits for a reader to let go of the file it replaces (Windows), and the
#: first pause between tries (doubling).
REPLACE_WAIT_SECONDS = 8.0
REPLACE_FIRST_PAUSE = 0.05


def save_docx(doc, docx_path: str) -> None:
    """Write `doc` to `docx_path` whole or not at all: into a temporary file beside it, then
    `os.replace` (atomic on one volume). A reader -- a download, Approve copying the file to keep
    it -- never meets a half-written Word file, and a write that fails leaves the previous file as
    it was (docs/design/WORD_FILE_UPDATES.md, SD).

    On Windows a file another process (or thread) has open cannot be replaced: Python opens files
    without FILE_SHARE_DELETE, so a download being served, or a copy being taken, holds it. The
    replace is tried again with a growing pause for `REPLACE_WAIT_SECONDS`, then fails with the
    reason -- the previous file untouched, never a torn one. The new file takes the old one's
    permissions (`mkstemp` makes 0600 on POSIX), or the umask's for a first file."""
    import tempfile
    import time
    folder = os.path.dirname(os.path.abspath(docx_path)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".docx.tmp", dir=folder)   # never a *.docx
    os.close(fd)
    try:
        doc.save(tmp)
        _same_mode(tmp, docx_path)
        deadline = time.monotonic() + REPLACE_WAIT_SECONDS
        pause = REPLACE_FIRST_PAUSE
        while True:
            try:
                os.replace(tmp, docx_path)
                return
            except PermissionError as exc:
                if time.monotonic() >= deadline:
                    raise PermissionError(
                        exc.errno, "%s is held open by a reader (a download, an approval's "
                        "copy) and could not be replaced within %.0f s; the previous file is as it "
                        "was -- update it again once the reader is done"
                        % (docx_path, REPLACE_WAIT_SECONDS), docx_path) from exc
                time.sleep(pause)
                pause = min(pause * 2, 1.0)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _same_mode(tmp: str, target: str) -> None:
    """`tmp` gets `target`'s permission bits, or -- no target yet -- the umask's for a new file
    (0666 & ~umask), as a plain `open(path, "wb")` would have made it."""
    import shutil
    if os.path.exists(target):
        shutil.copymode(target, tmp)
        return
    if os.name == "nt":
        return                                  # mkstemp's file is writable; no bits to set
    mask = os.umask(0)
    os.umask(mask)
    os.chmod(tmp, 0o666 & ~mask)


# ---------------------------------------------------------------------------
# Model / config loading
# ---------------------------------------------------------------------------

def load_model_json(name: str) -> dict:
    """One model artifact, through the single gateway (doc 10, step 5).

    This was the Phase-4 bypass: it opened model/<name>.json directly, so it read files even
    when the run's model is in the database. `read_model_file` resolves whichever backing the
    run installed. Missing still yields {} — callers treat an absent artifact as empty.
    """
    from core.model_io import read_model_file
    try:
        return read_model_file(name, required=False, default={}) or {}
    except Exception:                    # unreadable/corrupt -> empty, as before
        return {}


def load_base_path() -> str:
    meta = load_model_json("metadata")
    return (meta.get("basePath") or "").strip()


def load_abbreviations(project_root: str, config: dict) -> dict:
    """Load abbreviations from the text file named by config (llm.abbreviationsPath).

    Format: one per line, 'abbrev: meaning' or 'abbrev=meaning'; # = comment.
    """
    path = (config.get("llm") or {}).get("abbreviationsPath", "").strip()
    if not path:
        return {}
    full_path = os.path.join(project_root, path) if not os.path.isabs(path) else path
    if not os.path.isfile(full_path):
        return {}
    result = {}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, _, v = line.partition(":")
                elif "=" in line:
                    k, _, v = line.partition("=")
                else:
                    continue
                k, v = k.strip(), v.strip()
                if k:
                    result[k] = v
        return result
    except OSError:
        return {}


# ---------------------------------------------------------------------------
# Leaf docx helpers
# ---------------------------------------------------------------------------

def set_cell_font(cell, font_pt, bold=False):
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.size = font_pt
            r.font.bold = bold


def add_horizontal_rule(doc) -> None:
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    pBdr.append(bottom)
    pPr.append(pBdr)


def add_para(doc, text, style="Normal"):
    return doc.add_paragraph(text, style=style)


def add_toc(doc) -> None:
    """Insert a Word automatic table of contents field followed by a page break."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    from docx.enum.text import WD_ALIGN_PARAGRAPH
    try:
        p_title = doc.add_paragraph("Contents", style="TOC Heading")
    except KeyError:
        from docx.shared import Pt
        p_title = doc.add_paragraph()
        run = p_title.add_run("Contents")
        run.font.size = Pt(16)
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in p_title.runs:
        run.bold = True

    p = doc.add_paragraph()

    run = p.add_run()
    fldChar = OxmlElement("w:fldChar")
    fldChar.set(qn("w:fldCharType"), "begin")
    fldChar.set(qn("w:dirty"), "true")
    run._r.append(fldChar)

    run2 = p.add_run()
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = ' TOC \\o "1-4" \\h \\z \\u '
    run2._r.append(instrText)

    run3 = p.add_run()
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "separate")
    run3._r.append(fldChar2)

    run4 = p.add_run()
    t = OxmlElement("w:t")
    t.text = "Right-click here and select 'Update Field' to populate the table of contents."
    run4._r.append(t)

    run5 = p.add_run()
    fldChar3 = OxmlElement("w:fldChar")
    fldChar3.set(qn("w:fldCharType"), "end")
    run5._r.append(fldChar3)

    doc.add_page_break()

    # Tell Word to update all fields (including this TOC) when the document is opened
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    doc.settings.element.append(update_fields)


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def build_cover_page(doc, project_name: str, group_name: str, version: str = "1.0.0",
                     copyright_text: str = "",
                     subtitle_prefix: str = "Software Detailed Design Specification") -> None:
    """Render the cover page (first page) of the DOCX.

    `subtitle_prefix` names the document; it defaults to the SWE.3 title so the
    detailed-design cover is byte-for-byte what it was before the extraction.
    """
    from datetime import date as _date
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    NAVY = RGBColor(30, 60, 120)
    DARK = RGBColor(60, 60, 60)
    ASSETS = os.path.join(PROJECT_ROOT, "engine", "assets")

    def _spacing(para, before=0, after=0):
        pPr = para._p.get_or_add_pPr()
        for old in pPr.findall(qn("w:spacing")):
            pPr.remove(old)
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:before"), str(before))
        sp.set(qn("w:after"),  str(after))
        pPr.append(sp)

    def _align(para, val="right"):
        pPr = para._p.get_or_add_pPr()
        for old in pPr.findall(qn("w:jc")):
            pPr.remove(old)
        jc = OxmlElement("w:jc")
        jc.set(qn("w:val"), val)
        pPr.append(jc)
        para.alignment = (WD_ALIGN_PARAGRAPH.RIGHT if val == "right" else
                          WD_ALIGN_PARAGRAPH.CENTER if val == "center" else
                          WD_ALIGN_PARAGRAPH.LEFT)

    def _run(para, text, size_pt, bold=False, color=None):
        r = para.add_run(text)
        r.bold = bold
        r.font.size = Pt(size_pt)
        if color:
            r.font.color.rgb = color
        return r

    def _double_underline(run, color_hex="1E3C78"):
        rPr = run._r.get_or_add_rPr()
        for old in rPr.findall(qn("w:u")):
            rPr.remove(old)
        u = OxmlElement("w:u")
        u.set(qn("w:val"),   "double")
        u.set(qn("w:color"), color_hex)
        u.set(qn("w:sz"),    "12")
        rPr.append(u)

    def _spacer(n=1):
        for _ in range(n):
            p = doc.add_paragraph()
            _spacing(p, 0, 0)

    section    = doc.sections[0]
    body_w_in  = (section.page_width / 914400) - (
        section.left_margin / 914400 + section.right_margin / 914400)

    _spacer(8)

    # Project name — largest, bold, double-underlined
    p_name = doc.add_paragraph()
    _spacing(p_name, before=0, after=120)
    _align(p_name, "right")
    r_name = _run(p_name, project_name, size_pt=36, bold=True, color=NAVY)
    _double_underline(r_name, "1E3C78")

    # Subtitle — single line, no dash
    p_sub = doc.add_paragraph()
    _spacing(p_sub, before=0, after=100)
    _align(p_sub, "right")
    _run(p_sub, f"{subtitle_prefix}  {group_name}", size_pt=16, bold=True, color=NAVY)

    # Version
    p_ver = doc.add_paragraph()
    _spacing(p_ver, before=0, after=60)
    _align(p_ver, "right")
    _run(p_ver, f"Version {version}", size_pt=12, color=DARK)

    # Date
    p_date = doc.add_paragraph()
    _spacing(p_date, before=0, after=400)
    _align(p_date, "right")
    _run(p_date, _date.today().strftime("%Y-%m-%d"), size_pt=12, color=DARK)

    # Copyright image — left-aligned
    cr_path = os.path.join(ASSETS, "copyright.png")
    p_cr = doc.add_paragraph()
    _spacing(p_cr, before=0, after=0)
    _align(p_cr, "left")
    if os.path.isfile(cr_path):
        p_cr.add_run().add_picture(cr_path, width=Inches(2.6))
    else:
        _run(p_cr, "© All Rights Reserved", size_pt=10, color=DARK)

    # Copyright sentence below the image
    _cr_text = copyright_text or f"© {_date.today().year} All Rights Reserved."
    p_cr_text = doc.add_paragraph()
    _spacing(p_cr_text, before=0, after=0)
    _align(p_cr_text, "left")
    _run(p_cr_text, _cr_text, size_pt=8, color=RGBColor(128, 128, 128))

    _spacer(4)

    # Bottom arc — full body width
    arc_path = os.path.join(ASSETS, "bottom_arc.png")
    p_arc = doc.add_paragraph()
    _spacing(p_arc, before=0, after=0)
    _align(p_arc, "center")
    if os.path.isfile(arc_path):
        p_arc.add_run().add_picture(arc_path, width=Inches(body_w_in))

    doc.add_page_break()
