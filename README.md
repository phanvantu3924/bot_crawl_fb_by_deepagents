# 📡 FB Collector — Hệ thống Thu thập & Phân tích Facebook (Deep Agent Edition)

> Hệ thống tự động hóa thu thập nội dung từ Facebook Groups, lưu trữ đa tầng và phân tích thông minh bằng Deep Agent (Gemini 2.5 Flash).

---

##  Kiến Trúc Hệ Thống

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│    Web UI    │◀────▶│  Flask API   │◀────▶│  Selenium    │
│ (Controller) │      │  (Python)    │      │ (Chrome/FB)  │
└──────────────┘      └──────┬───────┘      └──────────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
    ┌──────────────┐                  ┌──────────────┐
    │  Storage     │                  │  Deep Agent  │
    │ (SQLite/JSON)│◀────────────────▶│ (Gemini 2.5) │
    └──────────────┘                  └──────┬───────┘
            │                                │
            ▼                                ▼
    ┌──────────────┐                  ┌──────────────┐
    │ Google Sheets│                  │ Telegram Bot │
    │   (Backup)   │                  │ (Reports)    │
    └──────────────┘                  └──────────────┘
```

---

## 🌟 Tính Năng Nổi Bật

- **Linh hoạt & Đa dụng**: Không giới hạn chủ đề. Bạn chỉ cần nhập nhóm và từ khóa, hệ thống sẽ tự động quét và phân tích (Việc làm, Bất động sản, Tin tức, Sản phẩm...).
- **Deep Agent (AI)**: Sử dụng Gemini 2.5 Flash để đọc hiểu nội dung, phân loại thông tin và tóm tắt báo cáo một cách thông minh.
- **Bộ nhớ dài hạn (`AGENTS.md`)**: Agent tự động ghi chép các xu hướng quan trọng để cải thiện chất lượng báo cáo theo thời gian.
- **Lưu trữ đa tầng**:
  - `data/raw/*.json`: Lưu toàn bộ bài viết thô để Agent có thể tra cứu sâu.
  - `data/bot.db`: SQLite lưu trữ dữ liệu có cấu trúc, hỗ trợ lọc trùng bài viết (deduplication).
  - `Google Sheets`: Tự động đẩy dữ liệu lên Cloud làm backup hoặc chia sẻ với đội nhóm.
- **Tự động hóa hoàn toàn**: Tích hợp Scheduler chạy ngầm (Mặc định: 16:00 Quét bài, 16:10 Gửi báo cáo).

---

## 📂 Cấu Trúc Thư Mục

```
fb-collector/
├── main.py               # Entry point: Khởi chạy Flask + Scheduler
├── agent.py              # Logic của Deep Agent & Tools phân tích
├── AGENTS.md             # Bộ nhớ dài hạn của Agent
├── config.json           # Cấu hình hệ thống (Cookies, Groups, Keys...)
├── requirements.txt      # Thư viện Python cần thiết
├── data/                 # Thư mục chứa SQLite & JSON raw data
├── app/                  # Package chính của Flask app
│   ├── job.py            # Tiến trình thu thập background
│   ├── routes.py         # Định nghĩa các API endpoints
│   ├── storage.py        # Quản lý lưu trữ SQLite & JSON
│   ├── scraper.py        # Chrome Automation client
│   └── sheets.py         # Google Sheets integration
└── templates/            # Giao diện Web (Dashboard)
```

---

## 🚀 Hướng Dẫn Cài Đặt

### Cách 1: Sử dụng Docker (Khuyến nghị)

Đây là cách nhanh nhất để có đầy đủ môi trường Chrome/Selenium mà không cần cài đặt thủ công.

```bash
# 1. Khởi chạy toàn bộ stack
docker compose up -d

# 2. Truy cập Dashboard
http://localhost:5001
```

### Cách 2: Chạy trực tiếp trên máy (Python)

```bash
# 1. Cài đặt dependencies
pip install -r requirements.txt

# 2. Chạy ứng dụng
python main.py
```
*Lưu ý: Bạn cần có Chrome browser và Chromedriver tương ứng trong máy.*

---

## ⚙️ Cấu Hình Quan Trọng

### 1. Facebook Cookies
Truy cập Facebook trên trình duyệt, mở DevTools (F12) -> Network. Chọn một request bất kỳ và copy toàn bộ nội dung trong header `Cookie`. Dán vào Dashboard để hệ thống có thể đăng nhập.

### 2. Deep Agent (Gemini API)
Lấy API Key tại [Google AI Studio](https://aistudio.google.com/). Agent sẽ dùng Key này để thực hiện các tác vụ phân tích cấp cao.

### 3. Telegram Reporting
1. Chat với `@BotFather` để tạo bot và lấy `TOKEN`.
2. Thêm bot vào Channel/Group của bạn với quyền Admin.
3. Lấy `Chat ID` của Channel/Group và dán vào phần cấu hình báo cáo.

---

## 🔌 API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET    | `/` | Giao diện Dashboard chính |
| POST   | `/api/run` | Kích hoạt quét bài thủ công |
| POST   | `/api/report` | Kích hoạt Agent tạo báo cáo ngay lập tức |
| GET    | `/api/stats` | Lấy thống kê nhanh từ SQLite |
| POST   | `/api/config/save` | Lưu cấu hình vào config.json |

---

## 📄 License & Lưu ý

- **Mục đích**: Dự án phục vụ nghiên cứu và học tập. Vui lòng tuân thủ điều khoản sử dụng của Facebook.
- **Bảo mật**: Tuyệt đối không chia sẻ file `config.json` hoặc `.env` chứa Token/Cookie của bạn.

---
*Phát triển bởi DeepAgents Team.*
