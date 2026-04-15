# TESTING.md — Testing Practices

## Test Framework

**None.** No test files, no test runner configuration, no CI pipeline found in the repository.

```
e:\bot_fixed\
├── (no tests/ directory)
├── (no pytest.ini / setup.cfg / pyproject.toml)
├── (no .github/workflows/)
└── (no Makefile with test targets)
```

## Current Verification Approach

All verification is manual and runtime-based:

| Verification type | How it's done |
|-------------------|---------------|
| Scraper working | Run via Web UI, watch live log |
| Report generation | Click "Tạo báo cáo" in dashboard, check Telegram |
| Storage working | Check `data/raw/*.json` and `data/bot.db` |
| Google Sheets | Verify new rows in spreadsheet |
| Agent memory | Check `AGENTS.md` for new entries |
| Config save/load | Use dashboard settings panel |

## Testability Assessment

### Easy to test (pure functions)
- `storage.py`: `_raw_path()`, `raw_posts_as_text()`, `get_today_stats()` — can be unit tested with temp dirs
- `scraper.py`: `_keyword_match()`, `_parse_relative_time()`, `_extract_reaction_count()` — pure functions, no selenium needed
- `sheets.py`: `get_current_sheet_name()`, `get_current_report_name()` — trivial

### Hard to test (external dependencies)
- `FacebookScraper.scrape_group()` — requires Chrome + active FB session
- `GoogleSheetsManager.append_posts()` — requires live Sheets credentials
- `run_daily_report()` — requires Gemini API key + Telegram bot
- APScheduler jobs — require timing coordination

## Recommended Test Structure (not yet implemented)

```
tests/
├── unit/
│   ├── test_storage.py       # JSON + SQLite operations with tmp dirs
│   ├── test_scraper_utils.py # Pure function tests
│   └── test_sheets_utils.py  # Date-based naming functions
├── integration/
│   └── test_routes.py        # Flask test client, mock storage
└── conftest.py               # Shared fixtures
```

## Known Manual Test Procedure

Based on project history and `config/fb-daily-report.json`:

1. Start container: `docker-compose up -d`
2. Open dashboard: `http://localhost:5001`
3. Load config from settings tab
4. Click "Bắt đầu thu thập" — watch logs
5. Verify `data/raw/YYYY-MM-DD.json` has entries
6. Click "Tạo báo cáo" — check Telegram channel
7. Verify `AGENTS.md` updated if trends detected
