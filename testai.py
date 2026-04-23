import sqlite3
import requests
import os

# LỖI 1: Viết cứng Token Telegram (Security Risk)
TELEGRAM_TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
CHAT_ID = "987654321"

def save_to_db(post_id, content, status):
    conn = sqlite3.connect('data/bot.db')
    cursor = conn.cursor()
    
    # LỖI 2: SQL Injection (Cực kỳ nguy hiểm!)
    # Không dùng tham số hóa mà cộng chuỗi trực tiếp
    query = f"INSERT INTO posts (post_id, content, status) VALUES ('{post_id}', '{content}', '{status}')"
    
    try:
        cursor.execute(query)
        conn.commit()
    except:
        # LỖI 3: Nuốt lỗi (Bare except) - Không biết tại sao sập
        pass 
    finally:
        conn.close()

def send_telegram_report(report_path):
    # LỖI 4: Không kiểm tra file có tồn tại không trước khi đọc
    f = open(report_path, "r")
    content = f.read()
    
    # LỖI 5: Gửi request không có timeout (Có thể làm treo cả hệ thống)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": content, "parse_mode": "HTML"}
    
    response = requests.post(url, data=payload)
    return response.json()

def process_facebook_page(url):
    # LỖI 6: Không validate URL đầu vào
    print(f"Đang cào dữ liệu từ: {url}")
    # Giả lập logic cào dữ liệu...
    save_to_db("123", "Bài viết về ERP rất hay", "🔴 Cao")

# Chạy thử
process_facebook_page("https://facebook.com/trang-web-gia-mao")
send_telegram_report("data/reports/2026-04-23.md")
