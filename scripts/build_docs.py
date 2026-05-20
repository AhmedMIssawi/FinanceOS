r"""Generate README.pdf and README.txt from FinanceOS.md.

One-shot tool — re-run this after editing FinanceOS.md to refresh the
shippable docs.

Run from the project root with the project venv:
    .\.venv\Scripts\python.exe scripts\build_docs.py

Requires (already installed in dev venv, not in app requirements.txt):
    pip install markdown xhtml2pdf
"""
from pathlib import Path

import markdown
from xhtml2pdf import pisa

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "FinanceOS.md"
PDF_OUT = PROJECT_ROOT / "README.pdf"
TXT_OUT = PROJECT_ROOT / "README.txt"

# xhtml2pdf renders with built-in fonts (Helvetica family) which lack
# emoji glyphs — they'd show as boxes. Replace with ASCII equivalents
# before parsing so the PDF stays readable everywhere.
ASCII_REPLACEMENTS = {
    "🎉": "[*]",
    "✅": "(yes)",
    "✓": "(yes)",
    "✗": "(no)",
    "⚠": "(!)",
    "☐": "[ ]",
    "⭐": "*",
    "🏠": "",
    "💳": "",
    "💸": "",
    "📋": "",
    "🔥": "",
    "⚙️": "",
    "🗑️": "",
    "📊": "",
    "📈": "",
    "→": "->",
    "—": " - ",
    "…": "...",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "•": "*",
}

CSS = """
@page { size: letter; margin: 0.8in 0.75in; }
body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #222;
}
h1 {
    color: #1f4e79;
    font-size: 22pt;
    margin-top: 12pt;
    margin-bottom: 8pt;
    border-bottom: 1.5pt solid #1f4e79;
    padding-bottom: 4pt;
}
h2 {
    color: #2e75b6;
    font-size: 16pt;
    margin-top: 14pt;
    margin-bottom: 6pt;
}
h3 {
    color: #1f4e79;
    font-size: 12.5pt;
    margin-top: 10pt;
    margin-bottom: 4pt;
}
h4 { color: #444; font-size: 11pt; margin-top: 8pt; margin-bottom: 4pt; }
p, li { margin: 3pt 0; }
ul, ol { margin: 4pt 0 6pt 18pt; }
table {
    border-collapse: collapse;
    margin: 8pt 0;
    width: 100%;
}
th, td {
    border: 0.5pt solid #888;
    padding: 4pt 6pt;
    text-align: left;
    font-size: 9.5pt;
    vertical-align: top;
}
th { background-color: #e8e8e8; font-weight: bold; }
code {
    background-color: #f0f0f0;
    padding: 1pt 3pt;
    font-family: "Courier New", Courier, monospace;
    font-size: 9.5pt;
    color: #b03060;
}
pre {
    background-color: #f4f4f4;
    padding: 6pt 8pt;
    border-left: 2pt solid #888;
    font-family: "Courier New", Courier, monospace;
    font-size: 9pt;
    margin: 6pt 0;
}
pre code { background: none; color: #222; padding: 0; }
hr { border: 0; border-top: 0.5pt solid #aaa; margin: 12pt 0; }
strong { color: #1a1a1a; }
"""


def _to_ascii(text: str) -> str:
    for src, dst in ASCII_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text


def build_pdf() -> None:
    md_content = SOURCE.read_text(encoding="utf-8")
    md_content = _to_ascii(md_content)
    html_body = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    full_html = (
        '<html><head><meta charset="utf-8">'
        f"<style>{CSS}</style></head><body>{html_body}</body></html>"
    )
    with open(PDF_OUT, "wb") as f:
        result = pisa.CreatePDF(full_html, dest=f, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF generation failed with {result.err} errors")
    print(f"Wrote: {PDF_OUT} ({PDF_OUT.stat().st_size // 1024} KB)")


def build_txt() -> None:
    """A short, no-frills quickstart that points at the PDF and the .md."""
    txt = """\
FinanceOS — Quick Start
=======================

A private, fully offline personal finance app for tracking expenses,
managing debts, and hitting savings goals.

FULL DOCUMENTATION
------------------
- README.pdf      Professional formatted version (open with any PDF reader)
- FinanceOS.md    Markdown source (open with any text editor or VS Code)

These three files contain identical content; pick whichever you prefer.

INSTALL (FIRST TIME ONLY)
-------------------------
1. Open PowerShell in this folder.
2. Run these three commands:

     py -m venv .venv
     .\\.venv\\Scripts\\Activate.ps1
     pip install -r requirements.txt

   If "Activate.ps1 cannot be loaded", first run (once):
     Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

RUN
---
Two ways:

  launch.vbs  -- silent, no terminal window (recommended for daily use)
  run.bat     -- shows a terminal with logs (use when debugging a problem)

Either way, your default browser opens at http://127.0.0.1:8501.

To STOP the app:
  - If launched via launch.vbs:  double-click stop.bat
  - If launched via run.bat:     close the terminal window

WHERE YOUR DATA LIVES
---------------------
- Database:  data/finance.db   (single SQLite file)
- Backups:   data/backups/     (daily, last 14 days kept)

The app binds to 127.0.0.1 only -- no other device on your network can reach it.

NEXT STEPS
----------
Open README.pdf or FinanceOS.md for the full guide:
  - Each page explained (Dashboard, Accounts, Transactions, Budgets, Debts, Settings)
  - Common workflows (paying credit cards, lending to friends, tracking coins, etc.)
  - Auto-archive behavior for paid-off loans and financing
  - Privacy, backups, and how to share the app with testers
  - Troubleshooting and known limitations

FEEDBACK
--------
Testers: keep a notepad open as you use the app. Note:
  - Anything confusing
  - Anything you tried to do that didn't work
  - Features that were missing
  - Numbers that looked wrong

That feedback shapes the next version.
"""
    TXT_OUT.write_text(txt, encoding="utf-8")
    print(f"Wrote: {TXT_OUT} ({TXT_OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build_pdf()
    build_txt()
    print("\nDone. Ship README.pdf to testers; keep FinanceOS.md as the editable source.")
