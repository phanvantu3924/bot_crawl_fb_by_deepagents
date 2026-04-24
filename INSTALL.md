#  FB Page Monitor — Hướng dẫn vận hành

## Khởi động

```bash
# Build và chạy lần đầu
docker compose up --build -d

# Khởi động lại (không build lại)
docker compose up -d

# Dừng bot
docker compose down
```

---

## Xem log

```bash
# Xem log realtime (Ctrl+C để thoát)
docker logs -f fb-page-monitor

# Xem 100 dòng log gần nhất
docker logs --tail 100 fb-page-monitor

# Xem log từ file (bên trong container)
docker exec fb-page-monitor tail -f logs/app.log

# Xem 200 dòng cuối từ file log
docker exec fb-page-monitor tail -n 200 logs/app.log
```

---

## Reset dữ liệu (khi test xong muốn xóa sạch)

```bash
# Xóa JSON raw + SQLite hôm nay
docker exec fb-page-monitor sh -c "rm -f data/raw/$(date +%Y-%m-%d).json && rm -f data/bot.db && echo Done"

# Xóa toàn bộ data (tất cả ngày)
docker exec fb-page-monitor sh -c "rm -rf data/raw/*.json data/bot.db && echo Done"

# Xóa cache LLM (nếu muốn chạy lại analyzer từ đầu)
docker exec fb-page-monitor sh -c "rm -rf data/cache/*.json && echo Done"

# Xóa báo cáo cũ
docker exec fb-page-monitor sh -c "rm -rf data/reports/*.md && echo Done"

# Xóa TẤT CẢ (raw + db + cache + reports)
docker exec fb-page-monitor sh -c "rm -rf data/raw/*.json data/bot.db data/cache/*.json data/reports/*.md && echo Done"
```

> **Lưu ý:** Google Sheets KHÔNG tự xóa — phải xóa thủ công tab `FB_Posts_YYYY-MM-DD` trên Sheets nếu muốn reset hoàn toàn.

---

## Kiểm tra dữ liệu bên trong container

```bash
# Xem danh sách file data
docker exec fb-page-monitor ls -lh data/raw/ data/

# Đếm số bài trong JSON hôm nay
docker exec fb-page-monitor sh -c "cat data/raw/$(date +%Y-%m-%d).json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d),\"bài\")'"

# Xem 3 bài đầu tiên trong JSON
docker exec fb-page-monitor sh -c "cat data/raw/$(date +%Y-%m-%d).json | python3 -c 'import json,sys; [print(p[\"content\"][:80]) for p in json.load(sys.stdin)[:3]]'"
```

---

## Trigger thủ công (không chờ lịch)

Gọi API trong container (nếu có endpoint `/api/scrape`):
```bash
# Trigger scrape ngay
curl -X POST http://localhost:8000/api/scrape

# Trigger report ngay
curl -X POST http://localhost:8000/api/report
```

---

## Rebuild sau khi thay đổi code

```bash
# Rebuild image và restart
docker compose up --build -d

# Chỉ restart (không build lại — dùng khi chỉ đổi config.json)
docker compose restart fb-page-monitor
```

---

## Cấu trúc thư mục data (trong container)

```
data/
├── raw/
│   └── 2026-04-24.json     ← Bài thô theo ngày (scraper ghi vào)
├── bot.db                   ← SQLite: posts + reports đã xử lý
├── cache/
│   └── *.json               ← Cache kết quả LLM analyzer
└── reports/
    └── 2026-04-24.md        ← Báo cáo markdown theo ngày
```

---

## Cấu hình (`config.json`)

| Trường | Mô tả |
|---|---|
| `sources[].url` | URL group/page Facebook |
| `sources[].keywords` | Từ khóa lọc cho nguồn đó |
| `global_topics` | Từ khóa lọc chung (áp dụng cho tất cả nguồn) |
| `max_posts` | Số bài tối đa scrape mỗi nguồn |
| `days_back` | Số ngày nhìn lại (1 = chỉ hôm nay) |
| `headless` | `true` = Chrome ẩn, `false` = hiện browser |
