# CONVENTIONS.md — Code Conventions & Patterns

## Code Style

- **Language**: Python 3.11, no type checker enforced (some type hints used)
- **Docstrings**: Short triple-quoted docstrings on most public functions and classes
- **Comments**: Inline comments in Vietnamese (matching the project's target audience); structural banners use `# ── Section ─────` separators
- **Encoding**: All files explicitly open with `encoding="utf-8"`
- **Imports**: Standard library → third-party → local, separated by blank lines (not always consistent)

## Error Handling

### Pattern: Try/Except with logging

All external calls are wrapped in `try/except`:
```python
try:
    result = external_call()
    logger.info("✅ Success message")
except Exception as e:
    logger.error(f"❌ Error context: {e}")
```

### API responses
Flask routes return `jsonify({"success": bool, "message": str})` with appropriate HTTP status codes:
- `200` — success (implicit)
- `400` — validation/business rule errors
- `500` — unexpected server errors

### Scraper errors
Per-group errors are caught and appended to `scrape_status["errors"]` without stopping the run:
```python
except Exception as e:
    err = f"❌ Lỗi {group_name}: {e}"
    emit_log(err, "error")
    scrape_status["errors"].append(err)
```

### Storage errors
`save_raw_posts()` catches `json.JSONDecodeError` and `OSError` when reading existing files, defaulting to empty list. SQLite uses context managers (`with conn:`) for implicit commit/rollback.

## Logging

Standard `logging` module. Logger initialized per module:
```python
logger = logging.getLogger(__name__)
```

Root config in `main.py`:
- Level: `INFO`
- Format: `%(asctime)s [%(levelname)s] %(name)s — %(message)s`
- Handlers: `StreamHandler` + `FileHandler("logs/app.log")`

Log messages use emoji prefixes for visual scanning:
- `✅` success, `❌` error, `⚠️` warning, `🚀` start, `🎉` complete, `⏰` scheduler

Web UI log via `emit_log()` — appends to `scrape_status["log"]` (capped at 200 entries).

## Module Responsibilities (clear separation)

| Module | Responsibility |
|--------|---------------|
| `main.py` | Bootstrap only — no business logic |
| `routes.py` | HTTP layer only — delegates to job/agent/storage |
| `scraper.py` | Selenium only — knows nothing about storage |
| `job.py` | Orchestration only — calls scraper + storage |
| `agent.py` | AI reasoning only — calls storage via tools |
| `storage.py` | Persistence only — no HTTP, no scraping |
| `sheets.py` | Google Sheets only — no other persistence |

## Dependency Injection Pattern

Config dict is passed explicitly through the call chain rather than using global state:
```python
# main.py
run_scrape_job(config)      # config passed explicitly
run_daily_report(config)    # config passed explicitly
```

Tools in `agent.py` use closures to capture config:
```python
def _make_tools(config: dict):
    def read_today_posts(keyword=None) -> str:
        ...  # config captured via closure
    return [read_today_posts, ...]
```

## Telegram Message Formatting

**Always use HTML parse mode** — never Markdown:
```python
"parse_mode": "HTML"
```

Allowed tags: `<b>`, `<i>`, `<code>`  
Forbidden characters in report text: `*`, `_`  
System prompt explicitly instructs agent: *"Không dùng ký tự * hay _"*

## Global State Pattern

`scrape_status` dict in `job.py` is the shared state between scraper thread and API:
```python
scrape_status = {
    "running": bool,
    "progress": int,
    "total": int,
    "current_group": str,
    "posts_collected": int,
    "errors": [],
    "log": []
}
```
Updated via `scrape_status.update({...})` and direct key assignment. No synchronization primitives used.

## Data Model

`FacebookPost` is a simple data class with `to_dict()` method:
```python
class FacebookPost:
    def to_dict(self):
        return self.__dict__
```

Callers handle both `FacebookPost` objects and plain dicts:
```python
d = post.to_dict() if hasattr(post, "to_dict") else post
```
