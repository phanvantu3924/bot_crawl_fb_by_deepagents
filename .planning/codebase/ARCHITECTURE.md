# ARCHITECTURE.md — System Architecture

## Pattern

**Monolith with background threads.** A single Flask application serves the web UI and REST API while background threads handle scraping and AI report generation. APScheduler runs scheduled jobs in the same process.

No microservices, no queue, no async framework — threads and a global state dict.

---

## Layers

```
┌─────────────────────────────────────────┐
│           Web UI (templates/index.html)  │  Single-page HTML/JS frontend
├─────────────────────────────────────────┤
│         Flask REST API  (app/routes.py) │  Blueprint "api", all endpoints
├──────────────┬──────────────────────────┤
│  Scrape Layer│      Agent Layer         │
│  app/job.py  │      app/agent.py        │  Background threads
│  app/scraper │   deepagents + Gemini    │
├──────────────┴──────────────────────────┤
│           Storage Layer                 │
│  app/storage.py   app/sheets.py         │  JSON raw | SQLite | Google Sheets
└─────────────────────────────────────────┘
         ↓                ↓
   data/raw/*.json    data/bot.db
```

---

## Components

### 1. Entry Point — `main.py`
- Initializes SQLite schema (`init_db()`)
- Creates Flask app (`create_app()`)
- Reads `config.json` for cron expressions
- Starts APScheduler with 2 jobs
- Exposes `app` variable for Gunicorn

### 2. Flask App Factory — `app/__init__.py`
- `create_app()` factory pattern
- Registers `api` Blueprint from `app/routes.py`
- Template/static folders point to parent directory

### 3. API Layer — `app/routes.py`
All endpoints in one file under the `api` Blueprint:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve SPA from templates/index.html |
| `/api/status` | GET | Scraper status dict |
| `/api/run` | POST | Start scrape (background thread) |
| `/api/stop` | POST | Signal scraper to stop |
| `/api/report` | POST | Trigger AI report (background thread) |
| `/api/stats` | GET | Today's SQLite counts |
| `/api/agent/memory` | GET/POST | Read/write AGENTS.md |
| `/api/config/save` | POST | Write config.json |
| `/api/config/load` | GET | Read config.json |

### 4. Scraper Pipeline — `app/job.py` + `app/scraper.py`

**Global state shared between thread and API:**
```python
scrape_status = {
    "running": bool, "progress": int, "total": int,
    "current_group": str, "posts_collected": int,
    "errors": [], "log": []   # log capped at 200 entries
}
```

**Flow:**
```
POST /api/run
  → validate config
  → set scrape_status["running"] = True
  → Thread(target=run_scrape_job)
      → GoogleSheetsManager
      → FacebookScraper (Selenium)
      → for each group_url:
          → scraper.scrape_group()
          → save_raw_posts() → data/raw/YYYY-MM-DD.json
          → upsert_posts()   → data/bot.db
          → sheets.append_posts() → Google Sheets
      → scraper.close()
      → scrape_status["running"] = False
```

### 5. AI Agent — `app/agent.py`

```
POST /api/report
  → Thread(target=run_daily_report)
      → create_report_agent(config)
          → ChatGoogleGenerativeAI(gemini-2.5-flash)
          → create_deep_agent(model, tools, system_prompt)
              → system_prompt = BASE_SYSTEM_PROMPT + AGENTS.md
      → agent.invoke({"messages": [user message]})
          → get_stats()
          → read_today_posts()
          → send_report_to_channel()  → Telegram (chunked HTML)
          → update_memory()           → AGENTS.md (optional)
```

### 6. Storage — `app/storage.py`

Two parallel stores operated simultaneously:
- **JSON**: Human-readable, agent-friendly, date-partitioned files in `data/raw/`
- **SQLite**: Structured, queryable, deduplication via `INSERT OR IGNORE`

`save_raw_posts()` and `upsert_posts()` both deduplicate using `post_id`.

### 7. Google Sheets — `app/sheets.py`

Third parallel write target. Deduplicates by checking existing URL values in column 6.
Creates a new sheet tab per day (`FB_Posts_YYYY-MM-DD`).

---

## Data Flow

```
Facebook Groups
    ↓ (Selenium)
FacebookScraper.scrape_group()
    ↓
[ FacebookPost objects ]
    ↓               ↓               ↓
save_raw_posts()  upsert_posts()  sheets.append_posts()
data/raw/         data/bot.db     Google Sheets
    ↓
raw_posts_as_text()
    ↓ (LangChain tool)
Deep Agent (Gemini)
    ↓
send_report_to_channel()
    ↓
Telegram Channel
    ↓
save_report()
data/bot.db (reports table)
```

---

## Thread Safety Notes

- `scrape_status` dict is mutated from both API thread (stop signal) and scraper thread — no lock used (race condition risk)
- `emit_log()` appends to `scrape_status["log"]` from scraper thread — no lock
- Config is read fresh from disk at each job execution (safe for scheduler)
- SQLite uses `with conn:` context manager (auto-commit/rollback)
