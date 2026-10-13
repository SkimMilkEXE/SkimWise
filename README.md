<p align="center">
  <img src="src/budget_tracker/assets/budget-icon.png" width="96" alt="SkimWise icon">
</p>

<h1 align="center">SkimWise</h1>

<p align="center">
  Skim the fat off your spending. A private, local-only budget app for Windows.<br>
  Part of the <a href="https://skimmilkexe.dev/software">SkimMilk.EXE</a> app family.
</p>

<p align="center">
  <img src="docs/screenshots/charts-dark.png" alt="SkimWise charts: spending by category, monthly spending and income vs expenses">
</p>

## Features

- **Import bank statements** as CSV or PDF. Map the columns once and save them as a *bank profile*, so later imports take one click
- **Handles messy exports**: account details above the table, separate debit/credit columns, `$1,234.56`, `(5.00)`, `5.00 DR`, European `1.234,56` and `;`-separated files, and dates with times
- **PDF statements** (text-based, e.g. M&T checking): transactions are read from the statement's sections, with the year and money in/out worked out for you
- **Duplicate detection**, so importing overlapping statements is safe
- **Rules** that sort transactions into categories automatically ("description contains STARBUCKS → Dining"), and offer to create themselves when you categorize something by hand
- **Monthly budgets** with progress bars that turn yellow near the limit and red over it
- **Charts**: spending by category, the monthly trend, and income vs expenses
- **Subscription finder**: spots recurring charges and totals them per month and per year
- **Bulk edits**: select several transactions to categorize or delete them together
- **Backup and restore**, plus **delete all data** for a fresh start
- **Demo data** to explore every screen before importing your own
- **Your colors**: pick the background and the colors for amounts, budget bars and charts in **Settings → Colors…**, or use the **Color-blind friendly** preset (blue and amber instead of green and red). Budget status is always written out too ("near limit", "over budget"), so it never depends on color alone
- **Reading options** in **Settings → Reading**: the dyslexia-friendly **OpenDyslexic** or **Atkinson Hyperlegible** fonts, text at 125% or 150%, and striped table rows that help your eye follow a row
- Light and dark themes, and your choice of date formats

<p align="center">
  <img src="docs/screenshots/budgets.png" alt="Budgets tab with green, yellow and red progress bars">
</p>

![Transactions tab with categories, colored amounts and monthly totals](docs/screenshots/transactions.png)

## Install

Download `SkimWise.exe` from the [latest release](https://github.com/SkimMilkEXE/Budget-Tracker/releases/latest), put it anywhere and run it.

Needs Windows 10 or 11 (64-bit). Nothing else to install, because Python and everything else is bundled into the exe. Your data is saved in `%AppData%\SkimWise\budget.db`, and settings like the theme are saved in the registry under `HKEY_CURRENT_USER\Software\SkimWise`.

Windows SmartScreen may warn you because the exe isn't code-signed. Click **More info → Run anyway**.

## Is my data private?

Yes. SkimWise makes no network connections: no accounts, no cloud sync, no tracking and no analytics. Everything stays in one SQLite file on your PC (**Settings → About** shows where).

Because there's no cloud copy, use **Settings → Back up data…** now and then to keep a copy somewhere safe. **Settings → Delete all data…** wipes everything if you want to start over.

## Notes and limits

- **PDF statements need real text.** Statements downloaded from your bank's website work. Scanned paper statements are just pictures of text, so use your bank's CSV export for those.
- **PDF layouts vary by bank.** Reading is tuned for typical US checking statements (tested with M&T). The import always shows a preview before anything is saved, so check it the first time you import from a new bank.
- **Long PDF descriptions** that wrap onto a second line keep only the first line.
- **Custom backgrounds use Qt's standard look.** Windows 11's own buttons and headers can't be recolored, so with a custom background SkimWise switches to Qt's Fusion style. Click **Theme default** next to Background to get the Windows 11 look back.
- **One budget per category** applies to every month, so changing a limit also changes how past months compare against it.
- **Windows only** for now. A Linux build may come later.

## Build from source

Needs [Python 3.12+](https://www.python.org/downloads/).

```powershell
python -m venv .venv
.venv\Scripts\activate                   # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
python -m budget_tracker                 # run
python -m pytest --cov=budget_tracker    # run the tests
pip install -e ".[build]"
python scripts/build.py                  # build the release exe into dist/
```

### Tech

- Python 3.12 with [PySide6](https://doc.qt.io/qtforpython-6/) (Qt), using a layered design: UI → services → repositories
- [QtCharts](https://doc.qt.io/qt-6/qtcharts-index.html) for the charts
- SQLite for storage, with versioned schema migrations that upgrade older databases automatically
- [pypdf](https://github.com/py-pdf/pypdf) for reading PDF statements
- Money stored as integer cents, never floats
- [PyInstaller](https://pyinstaller.org/) for the single-file exe
- pytest tests for the core logic (CSV and PDF parsing, rules, budgets, recurring detection, backup/restore) plus headless UI tests that drive the real window, linted and formatted with [ruff](https://docs.astral.sh/ruff/)

```
src/budget_tracker/
  models/     transactions, categories, rules, bank profiles, recurring items
  db/         database connection, migrations and repositories (all the SQL)
  services/   csv and pdf import, rules, budgets, reports, recurring detection, backup, demo data
  ui/         main window, one view per tab, import dialog, settings
tests/        pytest suite + fake sample statements in tests/fixtures/
scripts/      build.py for the exe
```

## License

[MIT](LICENSE). Bundled third-party software and its licenses are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
