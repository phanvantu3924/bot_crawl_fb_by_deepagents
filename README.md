# Facebook Page Monitoring Agent

Công cụ tự động theo dõi, phân tích nội dung và gửi báo cáo từ các Facebook Pages/Groups.

## Kiến trúc

```
Orchestrator (DeepAgent)
    ├── Sub-Agent: Analyzer  — phân loại bài viết theo mức độ liên quan
    └── Sub-Agent: Reporter  — tạo báo cáo Markdown + Telegram HTML

Model: qwen3.5:35b  (via https://poc-ai.hawee.com.vn/ollama/v1)
```

## Tính năng

- **Thu thập tự động** bài viết từ nhiều Facebook Pages/Groups
- **Phân tích AI** — phân loại mức độ liên quan: 🔴 Cao / 🟡 Trung bình / 🟢 Thấp
- **Topics per-page** — mỗi Page có danh sách chủ đề theo dõi riêng
- **Báo cáo đầy đủ** (§4.4): tổng bài, khung giờ, bài liên quan, toàn bộ bài
- **Xuất file Markdown** — lưu tại `data/reports/YYYY-MM-DD.md`
- **Gửi Telegram** — HTML format chia nhỏ tự động
- **Dashboard** — lọc theo page, topic, ngày; chart 7 ngày
- **Chạy tự động** — APScheduler cron jobs
- **Deep Agent memory** — AGENTS.md làm bộ nhớ dài hạn

## Cài đặt

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
# Truy cập: http://localhost:5000
```

## Docker

```bash
docker compose up -d
```

## Cấu hình

Chỉnh sửa `config.json` hoặc dùng Web UI:

```json
{
  "pages": [
    {
      "url": "https://www.facebook.com/yourpage",
      "name": "Tên Page",
      "topics": ["ERP", "tuyển dụng"]
    }
  ],
  "global_topics": ["AI", "việc làm"],
  "tg_token": "...",
  "tg_chat_id": "...",
  "cron_scrape": "0 8 * * *",
  "cron_report": "30 8 * * *"
}
```

## Output

- `data/raw/YYYY-MM-DD.json` — dữ liệu thô từ scraper
- `data/reports/YYYY-MM-DD.md` — báo cáo Markdown hàng ngày
- `data/bot.db` — SQLite với kết quả analysis
- `AGENTS.md` — bộ nhớ dài hạn của Agent
