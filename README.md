# AI PDF Reader

A minimal, local-first AI-enhanced PDF reader. Upload a PDF, select words to build your vocabulary list, and generate rich entries (definition, synonyms, antonyms, complex example, and Bengali meaning) via an LLM.

## Features

- Upload and store PDFs locally
- Render PDFs in the browser via PDF.js
- Click-and-drag to select any word; it’s added to your list automatically
- Dashboard to view selected words
- One-click "Generate" to fetch definitions/synonyms/antonyms/example/Bengali meaning using Cerebras Cloud
- Data persists per-PDF; return later and pick up where you left off

## Tech stack

- Backend: Flask + SQLite (simple, portable)
- Frontend: HTML/CSS/JS + PDF.js (CDN)
- LLM: Cerebras Cloud SDK (`gpt-oss-120b`)

## Setup

1. Install Python 3.10+
2. Create and activate a virtual environment (recommended)
3. Install dependencies
4. Configure environment variables
5. Run the server and open the app

### 1) Create a virtual environment (Windows cmd)

```cmd
python -m venv .venv
".venv\\Scripts\\activate"
```

### 2) Install dependencies

```cmd
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Configure environment

Copy `.env.example` to `.env` and fill in your values, or set env vars directly.

Required:
- `CEREBRAS_API_KEY` — your Cerebras Cloud API key

Optional:
- `STORAGE_DIR` — directory for database and PDFs (default: `storage`)
- `FLASK_DEBUG=1` — enable hot reload

Windows cmd example (temporary for this session):

```cmd
set CEREBRAS_API_KEY=YOUR_KEY_HERE
set FLASK_DEBUG=1
```

### 4) Run

```cmd
:: Option A: one-click script (Windows)
scripts\run.cmd

:: Option B: direct Python entrypoint
python app.py
```

Then open:

- http://localhost:5000/

## Usage

- Upload a PDF using the Upload button
- Use your mouse to select a word in the PDF viewer; it’s added instantly to your list
- Click Generate to fetch entries for all words that don’t have details yet
- Return later; your PDF and word list are persisted

## Notes

- The app never hardcodes your API key; it reads from `CEREBRAS_API_KEY`. Do not commit your real key.
- If `CEREBRAS_API_KEY` isn’t set, the app falls back to a mock generator so you can test the flow without incurring costs.

## Tests

Run a tiny smoke test suite:

```cmd
set STORAGE_DIR=%CD%\temp_storage
pytest -q
```

If you don’t have `pytest`, install it:

```cmd
pip install pytest
```

## Roadmap

- Per-word regenerate button and delete
- Per-PDF notes/highlights
- User accounts and cloud sync (optional)
- Export word list to CSV/Anki
