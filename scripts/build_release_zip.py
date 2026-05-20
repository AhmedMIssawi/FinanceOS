"""Build a clean release ZIP for sharing with testers.

Run from the project root with the project venv:
    .\\.venv\\Scripts\\python.exe scripts\\build_release_zip.py

Produces  FinanceOS-<version>.zip  in the project root, containing a
single top-level FinanceOS/ folder that includes all source, docs, and
launcher scripts but NEVER includes:
  - .venv/        (tester creates their own with setup.bat)
  - data/         (your real finance data!)
  - .pytest_cache/, __pycache__/, *.pyc
  - .git/         (don't ship history with the ZIP)
  - the previous FinanceOS-*.zip itself (avoid self-inclusion loop)

Bump VERSION here before each release.
"""
import os
import zipfile
from pathlib import Path

VERSION = "1.4"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZIP_PATH = PROJECT_ROOT / f"FinanceOS-{VERSION}.zip"

# Folder names anywhere in the tree that should be skipped entirely.
EXCLUDE_DIRS = {
    ".venv",
    "data",
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".vscode",
    ".idea",
    ".streamlit",
}

# File patterns (suffix or exact name) to skip.
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".db", ".db-journal")
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}


def should_skip(rel_path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel_path.parts):
        return True
    if rel_path.name in EXCLUDE_NAMES:
        return True
    if rel_path.suffix in EXCLUDE_SUFFIXES:
        return True
    # Don't include any previously built release ZIPs.
    if rel_path.name.startswith("FinanceOS-") and rel_path.suffix == ".zip":
        return True
    return False


def build() -> Path:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            root_path = Path(root)
            # Prune skipped dirs in-place so os.walk doesn't descend into them.
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                src = root_path / name
                rel = src.relative_to(PROJECT_ROOT)
                if should_skip(rel):
                    continue
                # Place each file under a top-level FinanceOS/ folder inside the
                # ZIP so unzipping gives one tidy directory.
                arcname = Path("FinanceOS") / rel
                zf.write(src, arcname.as_posix())
                count += 1
    return ZIP_PATH


if __name__ == "__main__":
    out = build()
    size_kb = out.stat().st_size // 1024
    print(f"Wrote: {out}  ({size_kb} KB)")
    print()
    print("This ZIP is safe to share. It contains:")
    print("  - All source (Dashboard.py, pages/, core/, tests/, scripts/, conftest.py)")
    print("  - Setup/launch scripts (setup.bat, launch.vbs, run.bat, stop.bat)")
    print("  - Docs (FinanceOS.md, README.md, README.pdf, README.txt, CLAUDE.md)")
    print("  - Configuration (requirements.txt, .gitignore)")
    print()
    print("It does NOT contain:")
    print("  - data/        (your real finance data — never shared)")
    print("  - .venv/       (tester creates their own via setup.bat)")
    print("  - .git/        (no history)")
    print("  - cache files  (__pycache__, .pytest_cache, *.pyc)")
    print()
    print("Tester instructions:")
    print("  1. Download the ZIP")
    print("  2. Unzip — they get a FinanceOS/ folder")
    print("  3. Double-click setup.bat (one-time)")
    print("  4. Double-click launch.vbs to start")
