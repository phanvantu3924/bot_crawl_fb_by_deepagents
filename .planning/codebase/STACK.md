# STACK.md — Technology Stack

## Language & Runtime

| Component | Value |
|-----------|-------|
| Language | Python 3.11 |
| Runtime | CPython (python:3.11-slim Docker base) |
| Entry point | `main.py` |

## Web Framework

| Package | Version | Role |
|---------|---------|------|
| `flask` | ≥3.0.0 | HTTP server + REST API + Jinja2 rendering |
| `gunicorn` | ≥21.2.0 | Production WSGI server (2 workers, 300s timeout) |

Flask is organized as a single Blueprint (`api`) registered in `app/__init__.py`.

## Browser Automation

| Package | Version | Role |
|---------|---------|------|
| `selenium` | ≥4.18.0 | Chrome WebDriver control for Facebook scraping |
| `webdriver-manager` | ≥4.0.1 | Auto-downloads matching ChromeDriver binary |

Chrome runs in headless mode inside Docker. Arguments used:
- `--no-sandbox`, `--disable-dev-shm-usage` — critical for Docker/Linux
- `--disable-gpu`, `--window-size=1920,1080`
- Custom User-Agent spoofing

## AI / Agent Framework

| Package | Version | Role |
|---------|---------|------|
| `deepagents` | ≥0.1.0 | Deep Agent orchestration (LangChain-based) |
| `langchain` | ≥0.3.0 | Core LLM abstraction layer |
| `langchain-google-genai` | ≥2.0.0 | Gemini API integration via LangChain |

**LLM Model in use:** `gemini-2.5-flash` (configurable via `config.json` → `gemini_key`)

## Scheduling

| Package | Version | Role |
|---------|---------|------|
| `APScheduler` | ≥3.10.0 | Cron-based background job scheduler |

Timezone: `Asia/Ho_Chi_Minh`. Two cron jobs:
- `cron_scrape` — default `0 16 * * *` (4:00 PM daily)
- `cron_report` — default `10 16 * * *` (4:10 PM daily)

## Google Integration

| Package | Version | Role |
|---------|---------|------|
| `gspread` | ≥6.0.0 | Google Sheets API client |
| `google-auth` | ≥2.28.0 | OAuth2 / Service Account auth |
| `google-auth-oauthlib` | ≥1.2.0 | OAuth2 flow support |

Authentication via **Service Account** JSON (stored in `config.json` → `sheets_creds`).

## Utilities

| Package | Version | Role |
|---------|---------|------|
| `requests` | ≥2.31.0 | HTTP calls to Telegram Bot API |
| `python-dotenv` | ≥1.0.0 | Loads `.env` file into environment |

## Data Storage

| Store | Technology | Location |
|-------|-----------|----------|
| Raw posts (daily) | JSON files | `data/raw/YYYY-MM-DD.json` |
| Processed posts | SQLite | `data/bot.db` |
| Reports | SQLite (table: `reports`) | `data/bot.db` |
| Long-term agent memory | Markdown file | `AGENTS.md` |

## Configuration

All runtime config is in `config.json` (root level). Key fields:
- `cookie` — Facebook session cookie string
- `groups` — newline-separated list of FB group URLs
- `keywords` — list of filter keywords
- `sheets_id` — Google Sheets spreadsheet ID
- `sheets_creds` — Service Account JSON (embedded)
- `max_posts`, `days_back`, `headless` — scraper tuning
- `tg_token`, `tg_chat_id` — Telegram bot credentials
- `gemini_key` — Google Gemini API key

> ⚠️ `config.json` is gitignored (contains live credentials + cookies)

## Containerization

| File | Purpose |
|------|---------|
| `Dockerfile` | python:3.11-slim + Chrome + app |
| `docker-compose.yml` | Service definition, port 5001→5000, volumes |

`shm_size: '2gb'` and `/dev/shm` volume mount are required for Chrome stability.

## Frontend

Single-page application served by Flask from `templates/index.html` (~60KB).
No separate build step — pure HTML/CSS/JS served via Jinja2 `render_template`.
