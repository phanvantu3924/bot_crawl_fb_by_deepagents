"""
Quản lý Google Sheets
Xử lý xác thực, tạo sheet và ghi dữ liệu thu thập.
"""
import json
import logging
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# Các quyền truy cập cần thiết cho Google Sheets và Google Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Tiêu đề các cột trong Google Sheets (KHÔNG ĐỔI)
HEADERS = [
    "Ngày Thu Thập",
    "Nhóm",
    "URL Nhóm",
    "Tác Giả",
    "Nội Dung",
    "URL Bài Viết",
    "Thời Gian Đăng",
    "Lượt Thích",
    "Bình Luận",
    "Chia Sẻ",
    "Từ Khóa Khớp",
    "Post ID",
]

def get_current_sheet_name():
    """Tạo tên sheet dựa trên ngày hiện tại (VD: FB_Posts_2024-04-07)."""
    return f"FB_Posts_{datetime.now().strftime('%Y-%m-%d')}"

def get_current_report_name():
    """Tạo tên sheet báo cáo dựa trên ngày hiện tại (VD: Report_2024-04-07)."""
    return f"Report_{datetime.now().strftime('%Y-%m-%d')}"


class GoogleSheetsManager:
    def __init__(self, credentials_json: str, spreadsheet_id: str):
        """
        Khởi tạo quản lý Google Sheets.
        credentials_json: Chuỗi JSON chứa thông tin tài khoản dịch vụ (Service Account)
        spreadsheet_id: ID của file Google Spreadsheet mục tiêu
        """
        self.spreadsheet_id = spreadsheet_id
        self.client = self._authenticate(credentials_json)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)

    def _authenticate(self, credentials_json: str) -> gspread.Client:
        """Xác thực với Google bằng thông tin tài khoản dịch vụ."""
        try:
            # Chấp nhận cả chuỗi JSON và từ điển (dict)
            if isinstance(credentials_json, str):
                creds_dict = json.loads(credentials_json)
            else:
                creds_dict = credentials_json

            credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            client = gspread.authorize(credentials)
            logger.info("✅ Xác thực Google Sheets thành công")
            return client
        except Exception as e:
            raise Exception(f"Lỗi xác thực Google Sheets: {e}")

    def ensure_sheet_exists(self):
        """Kiểm tra và tạo sheet kèm tiêu đề theo ngày nêu chưa tồn tại."""
        sheet_name = get_current_sheet_name()
        report_name = get_current_report_name()

        try:
            sheet = self.spreadsheet.worksheet(sheet_name)
            # Kiểm tra tiêu đề cột hiện có
            existing_headers = sheet.row_values(1)
            if not existing_headers:
                sheet.insert_row(HEADERS, 1)
        except gspread.WorksheetNotFound:
            # Tạo mới sheet của ngày hôm nay
            sheet = self.spreadsheet.add_worksheet(
                title=sheet_name, rows=1000, cols=len(HEADERS)
            )
            sheet.insert_row(HEADERS, 1)

            # Định dạng hàng tiêu đề: màu nền xanh, chữ trắng đậm, căn giữa
            sheet.format("A1:L1", {
                "backgroundColor": {"red": 0.18, "green": 0.27, "blue": 0.6},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "horizontalAlignment": "CENTER",
            })
            logger.info(f"✅ Đã tạo sheet mới: '{sheet_name}'")

        # Đảm bảo có cả sheet báo cáo hằng ngày (Mới)
        try:
            self.spreadsheet.worksheet(report_name)
        except gspread.WorksheetNotFound:
            rsheet = self.spreadsheet.add_worksheet(
                title=report_name, rows=100, cols=5
            )
            rsheet.insert_row(["Ngày", "Nhóm", "Tổng Bài", "Keywords", "Ghi Chú"], 1)
            rsheet.format("A1:E1", {
                "backgroundColor": {"red": 0.1, "green": 0.45, "blue": 0.3},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "horizontalAlignment": "CENTER",
            })
            logger.info(f"✅ Đã tạo sheet báo cáo mới: '{report_name}'")

    def append_posts(self, posts: list) -> int:
        """Thêm danh sách các bài viết vào sheet, có kiểm tra trùng lặp."""
        if not posts:
            return 0

        sheet_name = get_current_sheet_name()
        sheet = self.spreadsheet.worksheet(sheet_name)
        
        # 1. Kiểm tra trùng lặp dựa trên dữ liệu TRONG NGÀY
        try:
            # Chỉ lấy các URL trong sheet ngày hiện tại để so sánh
            existing_urls = set(sheet.col_values(6))
        except Exception as e:
            logger.warning(f"⚠️ Cảnh báo: Không thể tải danh sách URL của today: {e}")
            existing_urls = set()

        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rows = []
        for post in posts:
            d = post.to_dict() if hasattr(post, "to_dict") else post
            url = d.get("post_url", "")
            
            # 2. Bỏ qua nếu bài viết đã tồn tại (dựa trên URL)
            if url and url in existing_urls:
                continue
                
            rows.append([
                today,
                d.get("group_name", ""),
                d.get("group_url", ""),
                d.get("author", ""),
                d.get("content", "")[:1500],  # Giới hạn ký tự của ô trong Sheets
                url,
                d.get("timestamp", ""),
                d.get("likes", 0),
                d.get("comments", 0),
                d.get("shares", 0),
                ", ".join(d.get("keywords_matched", [])) if isinstance(d.get("keywords_matched"), list) else d.get("keywords_matched", ""),
                d.get("post_id", ""),
            ])

        if not rows:
            logger.info("ℹ️ Không có bài mới (Tất cả bài quét được đều đã tồn tại trong Sheets).")
            return 0

        # 3. Chỉ thêm những hàng dữ liệu mới
        sheet.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"📊 Đã ghi thêm {len(rows)} bài mới (Bỏ qua {len(posts) - len(rows)} bài trùng)")
        return len(rows)

    def get_today_posts(self, date_str: Optional[str] = None) -> list[dict]:
        """Đọc danh sách bài viết theo ngày chỉ định."""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        sheet_name = f"FB_Posts_{date_str}"
        try:
            sheet = self.spreadsheet.worksheet(sheet_name)
            all_rows = sheet.get_all_records()
            return all_rows
        except gspread.WorksheetNotFound:
            return []

    def get_stats(self) -> dict:
        """Lấy các chỉ số thống kê cơ bản từ sheet hiện tại."""
        try:
            sheet_name = get_current_sheet_name()
            sheet = self.spreadsheet.worksheet(sheet_name)
            all_data = sheet.get_all_values()
            # Trừ 1 hàng tiêu đề; min 0 nếu sheet trống
            total_rows = max(0, len(all_data) - 1)

            return {
                "total_posts": total_rows,
                "today_posts": total_rows,   # sheet đặt tên theo ngày nên mọi row đều là hôm nay
                "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}",
            }
        except Exception as e:
            logger.error(f"Lỗi khi lấy thống kê: {e}")
            return {"total_posts": 0, "today_posts": 0}
