# INTEGRATIONS.md — External Integrations

## Facebook (Selenium Scraping)

**Type:** Browser automation (no official API)  
**Library:** `selenium` + `webdriver-manager`  
**Auth method:** Cookie injection (cookie string from `config.json` → `cookie`)

### How it works
1. Open `https://www.facebook.com` in headless Chrome
2. Parse cookie string → inject via `driver.add_cookie()`
3. Navigate to group URLs, scroll to load posts
4. Extract post elements via CSS selectors

### Key selectors used
- Feed container: `div[role="feed"] > div, div[role="article"]`
- Author: `h2 strong, h3 strong, a[role='link'] strong`
- Content: `div[data-ad-comet-preview="message"], div[dir="auto"]`
- Post URLs: `a[href*='/posts/'], a[href*='story_fbid']`
- Timestamps: `a[href*='/posts/'] abbr, abbr[data-utime]`

### Fragility notes
- Cookie sessions expire — must refresh manually
- Facebook DOM changes break CSS selectors
- `headless = False` hardcoded in `FacebookScraper.__init__` (ignores config flag)

---

## Google Sheets

**Type:** REST API via Service Account  
**Library:** `gspread` + `google-auth`  
**Auth:** Service Account JSON embedded in `config.json` → `sheets_creds`  
**Scopes:** `spreadsheets`, `drive`

### Operations
| Operation | Method |
|-----------|--------|
| Connect | `gspread.authorize(credentials)` → `open_by_key(spreadsheet_id)` |
| Create daily sheet | `add_worksheet(title=FB_Posts_YYYY-MM-DD)` |
| Append rows | `sheet.append_rows(rows, value_input_option="USER_ENTERED")` |
| Dedup check | `sheet.col_values(6)` → check URL column |

### Sheet naming convention
- Posts: `FB_Posts_YYYY-MM-DD`
- Reports: `Report_YYYY-MM-DD`

---

## Google Gemini AI

**Type:** REST API via LangChain  
**Library:** `langchain-google-genai`  
**Auth:** API key in `config.json` → `gemini_key`  
**Model:** `gemini-2.5-flash` (temperature: 0.3)

### Usage
- `ChatGoogleGenerativeAI` wrapped via `deepagents.create_deep_agent()`
- Invoked with messages list format
- System prompt = `BASE_SYSTEM_PROMPT` + `AGENTS.md` content (long-term memory)

### Agent tools exposed to LLM
| Tool | Purpose |
|------|---------|
| `read_today_posts(keyword)` | Read day's raw JSON |
| `read_posts_by_date(date_str, keyword)` | Read historical raw JSON |
| `get_stats()` | SQLite today stats |
| `send_report_to_channel(report)` | Send to Telegram |
| `update_memory(note)` | Append to `AGENTS.md` |

---

## Telegram Bot API

**Type:** REST API (direct HTTP)  
**Library:** `requests`  
**Auth:** Bot token in `config.json` → `tg_token`  
**Target:** Channel ID in `config.json` → `tg_chat_id`

### Operations
- `POST /sendMessage` with `parse_mode: HTML`
- Messages chunked to ≤4000 chars, split at line boundaries
- Disable web page preview enabled

### Known gotchas
- `_` characters in plain text cause parse errors in Markdown mode → HTML mode used instead
- `*` characters also forbidden — system prompt instructs agent to use only HTML tags

---

## SQLite (local)

**Type:** Embedded database  
**Location:** `data/bot.db`  
**Library:** Python stdlib `sqlite3`

### Tables
| Table | Columns | Purpose |
|-------|---------|---------|
| `posts` | id, post_id (UNIQUE), group_name, group_url, author, content, post_url, timestamp, likes, comments, shares, keywords, collected_at | Deduplicated post store |
| `reports` | id, date, summary, sent_at, tg_message_id | Report delivery history |

### Indexes
- `idx_posts_date` on `posts.collected_at`
- `idx_reports_date` on `reports.date`

---

## APScheduler (internal)

**Type:** In-process scheduler (not external service)  
**Library:** `APScheduler`  
**Scheduler type:** `BackgroundScheduler`
**Trigger type:** `CronTrigger` (from crontab string)

### Jobs
| Job ID | Default cron | Action |
|--------|-------------|--------|
| `scrape_job` | `0 16 * * *` | Runs `run_scrape_job(config)` |
| `report_job` | `10 16 * * *` | Runs `run_daily_report(config)` |

Config is re-read at each job execution so changes take effect after restart.
