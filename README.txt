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
     .\.venv\Scripts\Activate.ps1
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
