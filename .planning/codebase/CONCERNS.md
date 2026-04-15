# CONCERNS.md — Technical Debt & Known Issues

## 🔴 Critical Issues

### 1. Hardcoded `headless = False` ignoring config
**File:** `app/scraper.py:63`  
```python
def __init__(self, cookie_string: str, headless: bool = True):
    self.headless = False   # BUG: always False, ignores parameter
```
**Impact:** Chrome always runs in non-headless mode even when `config.json` sets `"headless": true`. In Docker this may still work because `--headless` arg is only added when `self.headless` is True — but config-controlled headless is broken.  
**Fix:** Change to `self.headless = headless`

### 2. Facebook cookie session expiry — no detection
**File:** `app/scraper.py`  
**Impact:** When cookies expire, scraper navigates to FB login page instead of group pages. It won't detect this — it'll attempt to scrape the login page and collect zero posts silently (no error thrown, just empty results).  
**Fix:** Add post-cookie-injection login check (verify `c_user` cookie exists, or check page URL/title after refresh).

### 3. No thread synchronization on shared state
**File:** `app/job.py`, `app/routes.py`  
**Impact:** `scrape_status` dict is mutated from both the scraper background thread and the Flask API thread. Race conditions possible (e.g., reading `"running"` while it's being set). Low frequency but non-zero risk.  
**Fix:** Use `threading.Lock()` around `scrape_status` mutations, or switch to `threading.Event` for stop signaling.

### 4. Bare `except:` in scraper
**File:** `app/scraper.py:297`  
```python
except:
    pass
```
**Impact:** Silently swallows all exceptions in `_parse_relative_time()` including `KeyboardInterrupt`, `SystemExit`. Can mask serious errors.  
**Fix:** Change to `except Exception: pass`

---

## 🟡 Significant Issues

### 5. `get_stats()` bug in `sheets.py`
**File:** `app/sheets.py:188`  
```python
"today_posts": today_rows,  # NameError: today_rows is not defined
```
**Impact:** `GoogleSheetsManager.get_stats()` will raise `NameError` if called. Not currently called from routes (uses SQLite `get_today_stats()` instead), so not user-visible yet.  
**Fix:** Either compute `today_rows` or remove the field.

### 6. File handle not closed in `update_memory()`
**File:** `app/agent.py:107`  
```python
AGENTS_MD.open("a", encoding="utf-8").write(entry)
# File handle never explicitly closed
```
**Impact:** File handle leak on each `update_memory()` call. CPython's garbage collector will eventually close it, but risky under load.  
**Fix:** Use context manager: `with AGENTS_MD.open("a", encoding="utf-8") as f: f.write(entry)`

### 7. Agent memory read/write race condition
**File:** `app/agent.py` + `app/routes.py`  
**Impact:** Both routes (`/api/agent/memory` POST) and the running agent (`update_memory` tool) write to `AGENTS.md`. If both run concurrently, content could be corrupted or partially overwritten.  
**Fix:** File-level lock, or merge atomic write with append operation.

### 8. Credentials stored in `config.json` (not environment variables)
**File:** `config.json`  
**Impact:** Gemini API key, Telegram bot token, Facebook session cookie, and Google Service Account private key are all stored in a single JSON file. While gitignored locally, this pattern is fragile:
- Any accidental git add would expose all credentials
- No rotation/expiry mechanism
- Docker bind mount (`.:/app`) means the whole filesystem is in the container

**Fix:** Move to `.env` (already exists but underutilized) or use Docker secrets.

### 9. `post_id` deduplication uses fragile hash-based fallback
**File:** `app/scraper.py:143-144`  
```python
txt = el.text[:50]
post_id = str(hash(txt))
```
**Impact:** Python's `hash()` is not stable across processes/versions. Two runs could generate different `post_id` for the same post. The `UNIQUE` constraint in SQLite could then allow duplicate posts.  
**Fix:** Use a deterministic hash like `hashlib.md5(txt.encode()).hexdigest()[:16]`

---

## 🟠 Technical Debt

### 10. No tests
**Impact:** Zero automated test coverage. Any change risks breaking existing functionality silently. Verifying changes requires manual Docker deployment.

### 11. `agent.py` listed as dead code in `.gitignore`
**File:** `.gitignore:21`  
```
# Dead code
agent.py
```
**Impact:** `app/agent.py` is actively used and critical. The comment suggests a root-level `agent.py` was deleted but is still listed. Misleading for future developers. Could accidentally cause `app/agent.py` to be ignored if gitignore patterns change.

### 12. `static/` folder missing
**File:** `app/__init__.py:7`  
```python
static_folder='../static'
```
**Impact:** Flask registered with a `static_folder` that doesn't exist. Currently harmless since all assets are inlined in `index.html`, but Flask may log warnings and static file serving would 404.

### 13. Chrome binary path managed by `webdriver-manager` at runtime
**Impact:** First run inside Docker downloads ChromeDriver from the internet. If the download host is unavailable or the Chrome/ChromeDriver version mismatch occurs, the container fails silently. No pinned ChromeDriver version.

### 14. Log capped at 200 entries but no frontend polling
**File:** `app/job.py:30-31`  
**Impact:** Web UI log panel shows logs but must poll `/api/status` to update. If polling interval is too slow, logs rotate out before user sees them. No WebSocket/SSE push.

### 15. `config.json` written without atomic swap
**File:** `app/routes.py:119-121`  
```python
with open("config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, ...)
```
**Impact:** If the process crashes mid-write, `config.json` is left in a corrupt/partial state. Next scheduler run reads broken JSON and silently skips all jobs.  
**Fix:** Write to `config.json.tmp`, then `os.replace()` atomically.

---

## 🔵 Security Notes

- **Facebook cookie in config.json**: Full session cookie string with `c_user`, `xs`, `fr` tokens — effectively root access to the FB account. Expiry is not tracked.
- **Google Service Account private key**: Full RSA private key embedded in `config.json`. If leaked, attacker gets permanent access to Google Sheets.
- **Telegram bot token**: Bearer token. If leaked, attacker can send messages to the channel.
- **Gemini API key**: If leaked, attacker can run up API billing.
- **No input validation on `/api/config/save`**: Any JSON body is written directly to `config.json`. No schema validation, no size limit.
- **No authentication on dashboard**: The web UI and all API endpoints are publicly accessible with no login requirement.
