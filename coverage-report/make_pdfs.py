"""Print the two reports in this folder to PDF:  python coverage-report/make_pdfs.py"""
import os, shutil, subprocess
from pathlib import Path

here = Path(__file__).resolve().parent
cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
browser = next((c for c in cands if os.path.exists(c)), None) or next(
    (shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome") if shutil.which(n)), None)
if not browser:
    raise SystemExit("No Chrome or Edge found: open the .html files in a browser and print them to PDF.")
for html in sorted(here.glob("*.html")):
    pdf = html.with_suffix(".pdf")
    for flag in ("--headless=new", "--headless"):
        subprocess.run([browser, flag, "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.as_uri()],
                       capture_output=True, timeout=600)
        if pdf.exists() and pdf.stat().st_size:
            break
    print(pdf if pdf.exists() else f"failed: {html.name}")
