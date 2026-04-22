# STRUCTURE.md — Directory Structure

## Root Layout

```
e:\bot_fixed\
├── main.py                 # Entry point: Flask app + APScheduler bootstrap
├── requirements.txt        # Python dependencies
├── config.json             # Runtime configuration (gitignored — contains secrets)
├── AGENTS.md               # Deep Agent long-term memory file
├── Dockerfile              # Container build: python:3.11-slim + Chrome
├── docker-compose.yml      # Service config: port 5001→5000, volumes
├── README.md               # Project documentation
├── .env                    # Environment variables (gitignored)
├── .gitignore              # Excludes config.json, .env, logs/, data/, etc.
│
├── app/                    # Main application package
│   ├── __init__.py         # Flask app factory (create_app)
│   ├── routes.py           # All REST API endpoints (Blueprint "api")
│   ├── scraper.py          # FacebookScraper + FacebookPost model
│   ├── job.py              # Scrape background job + scrape_status state
│   ├── agent.py            # Deep Agent: Gemini + tools + Telegram delivery
│   ├── storage.py          # Dual storage: JSON raw files + SQLite
│   └── sheets.py           # Google Sheets integration
│
├── templates/
│   └── index.html          # Single-page web dashboard (~60KB, all-in-one)
│
├── config/
│   └── fb-daily-report.json  # Sample/last report metadata (committed)
│
├── data/                   # Runtime data (gitignored)
│   ├── raw/                # Scraped posts: YYYY-MM-DD.json per day
│   └── bot.db              # SQLite database
│
└── logs/                   # Application logs (gitignored)
    └── app.log
```

## Key File Locations

| Purpose | File |
|---------|------|
| App entry (Gunicorn target) | `main.py` → exposes `app` |
| Flask factory | `app/__init__.py` → `create_app()` |
| All REST routes | `app/routes.py` → Blueprint `api` |
| Facebook scraping | `app/scraper.py` → `FacebookScraper`, `FacebookPost` |
| Background job runner | `app/job.py` → `run_scrape_job()`, `scrape_status` |
| AI reporting | `app/agent.py` → `run_daily_report()`, `create_report_agent()` |
| Data persistence | `app/storage.py` → `save_raw_posts()`, `upsert_posts()`, `init_db()` |
| Google Sheets | `app/sheets.py` → `GoogleSheetsManager` |
| Web frontend | `templates/index.html` |
| Runtime config | `config.json` (root) |
| Agent memory | `AGENTS.md` (root) |
| Daily raw data | `data/raw/YYYY-MM-DD.json` |
| SQLite DB | `data/bot.db` |

## Naming Conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase` (e.g., `FacebookScraper`, `GoogleSheetsManager`)
- **Functions**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `HEADERS`, `AGENTS_MD`, `BASE_SYSTEM_PROMPT`)
- **Private helpers**: `_leading_underscore` (e.g., `_init_driver`, `_raw_path`, `_make_tools`)
- **Config keys**: `snake_case` JSON strings (e.g., `tg_token`, `gemini_key`)

## What Is Gitignored

```
config.json        # Live credentials + Facebook cookies
.env               # Environment variables
credentials.json   # (legacy) Google credentials
logs/              # App logs
data/              # SQLite + raw JSON (runtime state)
config/*.json      # All config files EXCEPT fb-daily-report.json
agent.py           # Listed in .gitignore (dead code marker, but file exists in app/)
__pycache__/       # Python bytecode
env/, venv/, .venv/ # Virtual environments
.vscode/, .idea/   # IDE configs
```

> ⚠️ Note: `.gitignore` lists `agent.py` as "dead code" but the file actively exists and is used at `app/agent.py`. The gitignore entry likely refers to a root-level `agent.py` that was deleted.

## Static Assets

No `static/` directory exists yet (Flask factory references `../static` but it's absent).
All CSS, JS, and assets are inlined directly into `templates/index.html`.
