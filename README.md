# FinanceOS

Offline personal finance app. Runs locally in your browser via Streamlit
on `http://127.0.0.1:8501` — never exposed to the network.

## First-time setup

Open **PowerShell** in this folder (`C:\Users\wesa2\Projects\FinanceOS`)
and run these three commands once:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `Activate.ps1` is blocked by Windows execution policy, run this once
in the same PowerShell window:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

…then re-run the activate command.

## Run

Double-click `run.bat`. Your default browser opens to
`http://127.0.0.1:8501`. To stop, close the terminal window.

## Layout

- `Dashboard.py` — home page (Streamlit entry)
- `pages/` — other screens, auto-discovered by Streamlit
- `core/` — DB, models, money helpers, debt math, backup (added phase by phase)
- `data/` — SQLite db and backups, auto-created at runtime, never committed
- `requirements.txt` — Python dependencies
- `run.bat` — double-click launcher
- `CLAUDE.md` — context for Claude Code sessions

## Tests

```powershell
.\.venv\Scripts\Activate.ps1
pytest -v
```

## Status

- Phase 0 (setup + skeleton) — **DONE**
- Phase 1 (DB + models + categories + money helpers) — **DONE**
- Phase 2 (Accounts + Transactions screens) — **DONE**

See `CLAUDE.md` for next phase.
