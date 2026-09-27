# Multi-Database Entity Resolution & Unified Data Repository

**Live deployment**: https://sma-entity-resolution-production.up.railway.app

PRJ-07 submission. Ingests records from multiple datasets, normalizes fields to a
canonical schema, resolves duplicate entities across sources using blocking +
weighted fuzzy matching, and builds a deduplicated master repository through a
review UI.

## Architecture

- **Backend**: FastAPI + SQLite (`backend/`)
  - `normalize.py` — canonicalizes name/email/phone/address/etc. into comparable form
    (lowercasing, whitespace collapse, phone digit-only + last-10, street abbreviation).
  - `resolution.py` — blocks records by name-prefix/email/phone/zip to avoid an
    O(n^2) comparison, scores candidate pairs with a weighted `rapidfuzz` blend per
    field, then clusters matches above a threshold with union-find.
  - `db.py` — SQLite schema: `datasets`, `records`, `clusters`, `master_repository`.
  - `main.py` — REST API: dataset upload/mapping, resolution run, cluster review
    (confirm/reject), paginated master repository, CSV export.
- **Frontend**: static HTML/CSS/JS (`frontend/`), single page, four tabs:
  1. Ingest — upload CSV/JSON, map source columns to canonical fields.
  2. Resolve — run matching at an adjustable similarity threshold.
  3. Review Matches — side-by-side duplicate groups with per-field value picker;
     confirm merge or keep separate.
  4. Master Repository — paginated unified table + CSV export.

Unique (unmatched) records are auto-added to the master repository; only
multi-record clusters need manual review, since that's where merge decisions are
ambiguous.

## Running locally

### Command line

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r backend/requirements.txt
python run.py                   # or: cd backend && uvicorn main:app --reload --port 8000
```

Open http://127.0.0.1:8000

### VS Code / Antigravity

A `.venv` is already set up in this folder with dependencies installed, and
`.vscode/` is preconfigured:

1. Open this folder (`C:\SMAassignment`) in VS Code or Antigravity.
2. When prompted, select the interpreter at `.venv\Scripts\python.exe` (or
   `Ctrl+Shift+P` → "Python: Select Interpreter").
3. Press `F5` and pick **"Run Entity Resolution Server"** (or **"Run via
   Uvicorn (reload)"** for auto-reload on save) — both are defined in
   `.vscode/launch.json`.
4. Alternatively, `Ctrl+Shift+P` → "Tasks: Run Task" → **"Start server"**.
5. Open http://127.0.0.1:8000 in a browser.

Antigravity is VS Code-compatible, so the same `.vscode/launch.json`,
`tasks.json`, and interpreter settings work there without changes.

## Demo data

`sample_data/crm_export.csv` and `sample_data/newsletter_signups.csv` contain the
same ~4 people under differently formatted names/phones/addresses, to exercise
the matcher. Upload both, map columns, then run resolution.

## Notes

- No external AI API calls are required for the core matching (deterministic
  fuzzy-matching is more reliable and auditable for entity resolution than an
  LLM call per pair); the brief lists AI APIs as optional.
- For public deployment, this is a single FastAPI process serving both API and
  static frontend — deployable as-is to Render/Railway/Fly.io (swap SQLite file
  path to a persistent volume).
