"""Unit-test coverage summary + full test-case list, as two PDFs.

    python tools/coverage_report.py               # run the tests with coverage (about 20 min), then the PDFs
    python tools/coverage_report.py --lists-only  # only the test-case list, nothing run (about 1 min)

Writes into output-coverage-report/: ArtiFex_Unit_Test_Coverage_Report.pdf and
ArtiFex_Unit_Test_Case_List.pdf (and the .html they are printed from). A PDF needs Chrome, Chromium
or Edge on the machine; without one the .html files are left to open and print by hand.
Backend: tests/unit + tests/api (pytest; coverage needs pytest-cov). Web app: web-app's unit project
(vitest; coverage needs @vitest/coverage-v8). A missing tool is reported, never fatal.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output-coverage-report"
PY = sys.executable
TITLE = "ArtiFex"

COMPONENTS = [
    ("API server", ["api/*"]),
    ("Review and update of documents", ["engine/review/*"]),
    ("Core services", ["engine/core/*", "engine/utils.py"]),
    ("Code views", ["engine/views/*", "engine/run_views.py"]),
    ("Incremental generation", ["engine/incremental/*"]),
    ("C++ parsing", ["engine/parser.py"]),
    ("Behaviour diagrams", ["engine/behaviour_diagram/*"]),
    ("Model derivation and AI-written text", ["engine/model_deriver.py", "engine/llm_enrichment.py", "engine/llm_core/*"]),
    ("Word document export", ["engine/docx_exporter.py", "engine/swe4_exporter.py", "engine/docx_common.py"]),
    ("Flowcharts", ["engine/flowchart/*"]),
]
PYTEST_BASE = ["-o", "addopts=", "-q", "-p", "no:cacheprovider", "-p", "no:warnings", "--skip-pipeline"]


def say(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def has_module(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def ensure_tools(web: bool) -> None:
    """Install what coverage needs when it is missing (an online machine): pytest-cov, and the
    @vitest/coverage-v8 that matches the web app's vitest (npm --no-save: package.json unchanged)."""
    if not (has_module("pytest_cov") and has_module("coverage")):
        say("installing coverage + pytest-cov")
        subprocess.run([PY, "-m", "pip", "install", "-q", "coverage", "pytest-cov"])
        import importlib
        importlib.invalidate_caches()
    wa = ROOT / "web-app"
    if web and (wa / "node_modules" / "vitest").exists() and not (wa / "node_modules" / "@vitest" / "coverage-v8").exists():
        n = shutil.which("npm.cmd" if platform.system() == "Windows" else "npm") or shutil.which("npm")
        if n:
            ver = json.loads((wa / "node_modules" / "vitest" / "package.json").read_text(encoding="utf-8"))["version"]
            say(f"installing @vitest/coverage-v8@{ver}")
            subprocess.run([n, "install", "--no-save", f"@vitest/coverage-v8@{ver}"], cwd=wa)


def npx() -> str | None:
    return shutil.which("npx.cmd" if platform.system() == "Windows" else "npx") or shutil.which("npx")


# ---------------------------------------------------------------- backend
def backend_list() -> list[dict]:
    r = subprocess.run([PY, "-m", "pytest", "tests/unit", "tests/api", "--collect-only", *PYTEST_BASE],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = []
    for line in r.stdout.splitlines():
        if "::" in line and not line.startswith(" "):
            path, _, name = line.strip().partition("::")
            out.append({"file": path, "name": name, "result": "not run"})
    return out


def backend_run(workers: int) -> tuple[list[dict], dict | None]:
    """Run tests/unit + tests/api in `workers` parallel groups (+ api), with coverage when pytest-cov is
    installed. Returns (test results from junit, coverage per component or None)."""
    with_cov = has_module("pytest_cov") and has_module("coverage")
    if not with_cov:
        say("pytest-cov not installed: backend tests run without coverage (pip install pytest-cov)")
    files = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "tests/unit").glob("test_*.py"))
    groups = [files[i::workers] for i in range(workers)] + [["tests/api"]]
    procs = []
    for i, g in enumerate(groups):
        env = dict(os.environ, COVERAGE_FILE=str(OUT / f".coverage.g{i}"))
        cmd = [PY, "-m", "pytest", *g, *PYTEST_BASE, f"--junitxml={OUT / f'junit_g{i}.xml'}"]
        if with_cov:
            cmd += ["--cov=engine", "--cov=api", "--cov-report="]
        log = open(OUT / f"pytest_g{i}.log", "w", encoding="utf-8")
        procs.append((subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT), log))
    say(f"backend: {len(groups)} test groups running in parallel (logs in {OUT.name}/pytest_g*.log)")
    for p, log in procs:
        p.wait()
        log.close()
    results = []
    for i in range(len(groups)):
        x = OUT / f"junit_g{i}.xml"
        if not x.exists():
            continue
        for tc in ET.parse(x).getroot().iter("testcase"):
            cls = tc.get("classname", "")
            parts = cls.split(".")
            # tests.unit.test_x[.TestClass] -> tests/unit/test_x.py
            mod = [p for p in parts if p.startswith("test_")]
            file = "/".join(parts[: parts.index(mod[0]) + 1]) + ".py" if mod else cls
            name = (".".join(parts[parts.index(mod[0]) + 1:]) + "::" if mod and parts[-1] != mod[0] else "") + tc.get("name", "")
            res = "passed"
            if tc.find("failure") is not None:
                res = "failed"
            elif tc.find("error") is not None:
                res = "error"
            elif tc.find("skipped") is not None:
                res = "skipped"
            results.append({"file": file, "name": name, "result": res})
    cov = None
    if with_cov:
        import coverage
        data = [str(OUT / f".coverage.g{i}") for i in range(len(groups)) if (OUT / f".coverage.g{i}").exists()]
        c = coverage.Coverage(data_file=str(OUT / ".coverage"))
        c.combine(data, keep=False)
        c.save()
        c.load()
        os.chdir(ROOT)

        def pct(patterns):
            try:
                return round(c.report(include=patterns, file=io.StringIO()))
            except Exception:                       # noqa: BLE001 - no file matched
                return None
        cov = {name: pct(pats) for name, pats in COMPONENTS}
        cov["__engine"] = pct(["engine/*"])
        cov["__backend"] = pct(["engine/*", "api/*"])
    return results, cov


# ---------------------------------------------------------------- web app
def web_run(lists_only: bool) -> tuple[list[dict], float | None, str]:
    wa = ROOT / "web-app"
    n = npx()
    if not n or not (wa / "node_modules" / "vitest").exists():
        return [], None, "web app: node / vitest not installed here"
    if lists_only:
        r = subprocess.run([n, "vitest", "list", "--project", "unit"], cwd=wa, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        tests = []
        for line in r.stdout.splitlines():
            if " > " in line:
                f, _, rest = line.partition(" > ")
                tests.append({"file": f.replace("[unit] ", "").strip(), "name": rest.strip(), "result": "not run"})
        return tests, None, ""
    with_cov = (wa / "node_modules" / "@vitest" / "coverage-v8").exists()
    res_file = OUT / "web_results.json"
    cmd = [n, "vitest", "run", "--project", "unit", "--reporter=json", f"--outputFile={res_file}"]
    if with_cov:
        cmd += ["--coverage", "--coverage.provider=v8", "--coverage.include=src/**",
                "--coverage.reporter=json-summary", f"--coverage.reportsDirectory={OUT / 'web-coverage'}"]
    say("web app: tests running" + ("" if with_cov else " (no coverage: @vitest/coverage-v8 not installed)"))
    with open(OUT / "vitest.log", "w", encoding="utf-8") as log:
        subprocess.run(cmd, cwd=wa, stdout=log, stderr=subprocess.STDOUT)
    tests = []
    if res_file.exists():
        data = json.loads(res_file.read_text(encoding="utf-8"))
        for tr in data.get("testResults", []):
            f = os.path.relpath(tr.get("name", ""), wa).replace("\\", "/")
            for a in tr.get("assertionResults", []):
                st = {"passed": "passed", "failed": "failed", "pending": "skipped", "skipped": "skipped",
                      "todo": "skipped"}.get(a.get("status"), a.get("status", ""))
                tests.append({"file": f, "name": a.get("fullName") or a.get("title", ""), "result": st})
    pct = None
    summ = OUT / "web-coverage" / "coverage-summary.json"
    if summ.exists():
        pct = json.loads(summ.read_text(encoding="utf-8"))["total"]["lines"]["pct"]
    return tests, pct, "" if with_cov else "web app coverage not measured (@vitest/coverage-v8 not installed)"


# ---------------------------------------------------------------- html + pdf
CSS = """
@page { size: A4; margin: 16mm; }
body { font-family: "Segoe UI", Arial, sans-serif; color:#1f2933; font-size:10pt; line-height:1.4; margin:0; }
h1 { font-size:18pt; color:#0b3c5d; margin:0 0 2pt; } h2 { font-size:12pt; color:#0b3c5d; margin:14pt 0 5pt;
border-bottom:1px solid #d9e2ec; padding-bottom:2pt; } h3 { font-size:10pt; margin:10pt 0 3pt; color:#0b3c5d; }
.date { color:#52606d; margin-bottom:10pt; } .muted { color:#52606d; }
.kpis { display:flex; gap:10pt; } .kpi { flex:1; border:1px solid #d9e2ec; border-radius:6pt; padding:8pt 10pt;
background:#f5f8fb; } .kpi .v { font-size:22pt; font-weight:600; color:#0b3c5d; } .kpi .l { color:#52606d; }
table { width:100%; border-collapse:collapse; } th, td { text-align:left; padding:3pt 6pt; border-bottom:1px solid #e4e7eb; }
th { background:#0b3c5d; color:#fff; } td.r, th.r { text-align:right; } tr:nth-child(even) td { background:#f8fafc; }
.bar { display:inline-block; height:6pt; background:#2f80c3; border-radius:2pt; margin-right:5pt; }
.failed, .error { color:#b42318; font-weight:600; } .skipped { color:#8a6d00; } .passed { color:#1e7a34; }
ul { margin:3pt 0 0 14pt; padding:0; } td.n { width:82%; word-break:break-all; }
"""


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def counts(tests: list[dict]) -> dict:
    c = {}
    for t in tests:
        c[t["result"]] = c.get(t["result"], 0) + 1
    return c


def result_text(c: dict) -> str:
    total = sum(c.values())
    if not total:
        return "not available"
    if set(c) == {"not run"}:
        return f"{total} listed (not run)"
    parts = [f"{c.get('passed', 0)} passed"]
    for k in ("failed", "error", "skipped"):
        if c.get(k):
            parts.append(f"{c[k]} {k}")
    return ", ".join(parts)


def summary_html(today: str, cov: dict | None, web_pct, be: list, web: list, notes: list[str]) -> str:
    def kpi(v, label):
        return f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{label}</div></div>"
    be_v = f"{cov['__backend']}%" if cov and cov.get("__backend") is not None else "n/a"
    web_v = f"{round(web_pct)}%" if web_pct is not None else "n/a"
    rows = []
    comp = [(name, cov.get(name)) for name, _ in COMPONENTS] if cov else []
    if web_pct is not None:
        comp.append(("Web application", round(web_pct)))
    for name, v in sorted(comp, key=lambda x: -(x[1] or 0)):
        cell = "n/a" if v is None else f"<span class='bar' style='width:{v}px'></span>{v}%"
        rows.append(f"<tr><td>{html.escape(name)}</td><td class='r'>{cell}</td></tr>")
    comp_table = ("<h2>Results by component</h2><table><tr><th>Component</th><th class='r'>Coverage</th></tr>"
                  + "".join(rows) + "</table>") if rows else ""
    cb, cw = counts(be), counts(web)
    tests = ("<h2>Test results</h2><table><tr><th>Suite</th><th class='r'>Tests</th><th>Result</th></tr>"
             f"<tr><td>Backend</td><td class='r'>{len(be):,}</td><td>{result_text(cb)}</td></tr>"
             f"<tr><td>Web application</td><td class='r'>{len(web):,}</td><td>{result_text(cw)}</td></tr></table>")
    std = ["Word document export, flowcharts and the command-line interface are also exercised by end-to-end "
           "tests and by tests that start them as separate programs; these are not included in the figures, so "
           "their actual coverage is higher than shown.",
           "Internal developer tools are excluded.",
           "The full list of test cases is in the companion report, Unit Test Case List."]
    body = (f"<h1>{TITLE} — Unit Test Coverage Report</h1><div class='date'>{today}</div>"
            f"<h2>Summary</h2><div class='kpis'>{kpi(be_v, 'Backend (analysis engine and API server)')}"
            f"{kpi(web_v, 'Web application')}</div>"
            "<div class='muted'>Coverage is the share of the code that the automated unit tests exercise.</div>"
            f"{comp_table}{tests}<h2>Notes</h2><ul>"
            + "".join(f"<li>{html.escape(n)}</li>" for n in std + notes) + "</ul>")
    return page(f"{TITLE} — Unit Test Coverage Report", body)


def list_html(today: str, be: list, web: list) -> str:
    parts = [f"<h1>{TITLE} — Unit Test Case List</h1><div class='date'>{today}</div>"]
    for title, tests in (("Backend (analysis engine and API server)", be), ("Web application", web)):
        parts.append(f"<h2>{title} — {len(tests):,} tests: {result_text(counts(tests))}</h2>")
        by_file: dict[str, list] = {}
        for t in tests:
            by_file.setdefault(t["file"], []).append(t)
        for f in sorted(by_file):
            rows = "".join(f"<tr><td class='n'>{html.escape(t['name'])}</td>"
                           f"<td class='{t['result'].replace(' ', '')}'>{t['result']}</td></tr>" for t in by_file[f])
            parts.append(f"<h3>{html.escape(f)} ({len(by_file[f])})</h3><table>"
                         f"<tr><th>Test case</th><th>Result</th></tr>{rows}</table>")
    return page(f"{TITLE} — Unit Test Case List", "".join(parts))


def browser() -> str | None:
    cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
    for c in cands:
        if os.path.exists(c):
            return c
    for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"):
        p = shutil.which(n)
        if p:
            return p
    return None


def to_pdf(html_file: Path, pdf: Path) -> bool:
    b = browser()
    if not b:
        return False
    for flag in ("--headless=new", "--headless"):
        subprocess.run([b, flag, "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        html_file.resolve().as_uri()], capture_output=True, timeout=600)
        if pdf.exists() and pdf.stat().st_size > 0:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lists-only", action="store_true", help="only list the test cases (nothing run, about 1 min)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 3)),
                    help="parallel backend test groups (default: a third of the CPUs, at most 4)")
    ap.add_argument("--no-web", action="store_true", help="leave the web app out")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    today = dt.date.today().strftime("%d %B %Y")
    notes: list[str] = []
    started = dt.datetime.now()

    if a.lists_only:
        say("listing backend tests")
        be, cov = backend_list(), None
    else:
        ensure_tools(not a.no_web)
        say("backend: running tests with coverage (about 20 min)")
        be, cov = backend_run(a.workers)
        if not be:
            notes.append("Backend test results could not be read; see the pytest logs.")
    web, web_pct, msg = ([], None, "") if a.no_web else web_run(a.lists_only)
    if msg:
        notes.append(msg)
        say(msg)

    made = []
    files = [("ArtiFex_Unit_Test_Case_List", list_html(today, be, web))]
    if not a.lists_only:
        files.insert(0, ("ArtiFex_Unit_Test_Coverage_Report", summary_html(today, cov, web_pct, be, web, notes)))
    for stem, text in files:
        h = OUT / f"{stem}.html"
        h.write_text(text, encoding="utf-8")
        pdf = OUT / f"{stem}.pdf"
        made.append(pdf if to_pdf(h, pdf) else h)
    say(f"done in {(dt.datetime.now() - started).seconds // 60} min: backend {len(be):,} tests, web app {len(web):,} tests")
    if cov:
        say(f"coverage: backend {cov.get('__backend')}%, web app {web_pct if web_pct is not None else 'n/a'}%")
    for m in made:
        print("  ", m)
    if any(m.suffix == ".html" for m in made):
        print("   (no Chrome / Edge found: open the .html in a browser and print it to PDF)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
