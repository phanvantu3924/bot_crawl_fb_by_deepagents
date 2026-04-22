"""
Trình thu thập dữ liệu Facebook (Facebook Scraper)
Sử dụng Selenium để tự động hóa trình duyệt và trích xuất dữ liệu từ các nhóm.
"""
import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


class FacebookPost:
    """Đối tượng đại diện cho một bài viết Facebook."""

    def __init__(
        self,
        post_id: str,
        group_name: str,
        group_url: str,
        author: str,
        content: str,
        post_url: str,
        timestamp: str,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        keywords_matched: List[str] = None,
    ):
        self.post_id = post_id
        self.group_name = group_name
        self.group_url = group_url
        self.author = author
        self.content = content
        self.post_url = post_url
        self.timestamp = timestamp
        self.likes = likes
        self.comments = comments
        self.shares = shares
        self.keywords_matched = keywords_matched or []

    def to_dict(self):
        return self.__dict__


class FacebookScraper:
    def __init__(self, cookie_string: str, headless: bool = True):
        """
        Khởi tạo Facebook Scraper.
        cookie_string: Chuỗi cookie để đăng nhập
        headless: Chế độ ẩn danh (không hiện cửa sổ trình duyệt)
        """
        self.cookie_string = cookie_string
        self.headless = headless
        self.driver = self._init_driver()
        self._set_cookies()

    def _init_driver(self):
        """Khởi tạo Chrome WebDriver với các tùy chọn tối ưu."""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        
        # Các tùy chọn giúp chạy ổn định trên môi trường Docker/Linux
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Giả lập User-Agent của người dùng thật
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver

    def _set_cookies(self):
        """Dán cookie vào trình duyệt để vượt qua bước đăng nhập."""
        try:
            # Phải truy cập trang chủ trước khi dán cookie
            self.driver.get("https://www.facebook.com")
            time.sleep(2)

            cookies = self.cookie_string.split(";")
            for cookie in cookies:
                if "=" in cookie:
                    name, value = cookie.strip().split("=", 1)
                    self.driver.add_cookie({"name": name, "value": value, "domain": ".facebook.com"})
            
            logger.info("✅ Đã dán cookie thành công")
            self.driver.refresh()
            time.sleep(3)
        except Exception as e:
            logger.error(f"❌ Lỗi khi thiết lập cookie: {e}")

    def scrape_group(
        self,
        group_url: str,
        keywords: List[str] = None,
        max_posts: int = 50,
        days_back: int = 7,
    ) -> List[FacebookPost]:
        """
        Thu thập các bài viết từ một nhóm dựa trên từ khóa và thời gian.
        """
        if not group_url.startswith("http"):
            group_url = f"https://www.facebook.com/groups/{group_url}"

        logger.info(f"🌐 Đang truy cập nhóm: {group_url}")
        self.driver.get(group_url)
        time.sleep(5)

        collected = []
        seen_ids = set()
        cutoff_date = datetime.now() - timedelta(days=days_back)

        # Cuộn trang để tải thêm bài viết
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        
        while len(collected) < max_posts and scroll_attempts < 20:
            # Tìm các phần tử bài viết trực tiếp trên DOM của FB
            posts_els = self.driver.find_elements(By.CSS_SELECTOR, 'div[role="feed"] > div, div[role="article"]')
            
            for el in posts_els:
                try:
                    # Lấy định danh duy nhất của bài viết
                    post_id = el.get_attribute("aria-label") or el.get_attribute("id") or ""
                    if not post_id:
                        # Dùng hash nội dung để nhận diện nếu không có ID
                        txt = el.text[:50]
                        post_id = str(hash(txt))

                    if post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    # 1. Trích xuất Tác giả (Chỉ lấy trong phần Header)
                    author = "Ẩn danh"
                    author_els = el.find_elements(By.CSS_SELECTOR, "h2 strong, h3 strong, a[role='link'] strong")
                    if author_els:
                        author = author_els[0].text

                    # 2. Trích xuất Nội dung chính (Nhắm vào khung văn bản bài viết)
                    content_els = el.find_elements(
                        By.CSS_SELECTOR, 
                        'div[data-ad-comet-preview="message"], div[dir="auto"], div.xdj266r.x11i5rnm.xat24cr.x1mh8g0r'
                    )
                    
                    full_text = ""
                    if content_els:
                        for ce in content_els:
                            t = ce.text.strip()
                            if t and len(t) > 5:
                                full_text += t + "\n"
                    
                    # Nếu vẫn trống, lấy el.text nhưng sẽ làm sạch sau
                    if not full_text:
                        full_text = el.text
                    
                    # Làm sạch nội dung: Xóa các thông tin gây nhiễu
                    noise_patterns = [
                        r"\d+\s*(giờ|phút|giây|ngày|tuần|tháng|hour|min|sec|day|week)\s*·",
                        r"(Thích|Bình luận|Chia sẻ|Like|Comment|Share)\s*\d*",
                        author, # Xóa tên tác giả khỏi nội dung chính
                        r"Người đóng góp nhiều nhất",
                        r"Theo dõi",
                        r"Người tham gia ẩn danh\s*\d*"
                    ]
                    for p in noise_patterns:
                        full_text = re.sub(p, "", full_text, flags=re.IGNORECASE).strip()
                    
                    # Giảm bớt các dòng trống dư thừa
                    full_text = re.sub(r"\n{3,}", "\n\n", full_text)
                    content = full_text[:2000] if len(full_text) > 2000 else full_text

                    if not content or len(content) < 10:
                        continue

                    # Lọc theo từ khóa
                    matched = self._keyword_match(content, keywords) if keywords else ["*"]
                    if keywords and not matched:
                        continue

                    # 3. Trích xuất thời gian đăng bài
                    post_time = None
                    time_els = el.find_elements(By.CSS_SELECTOR, "a[href*='/posts/'] abbr, abbr[data-utime], a abbr, span[id*='jsc_c']")
                    for te in time_els:
                        ts = te.get_attribute("data-utime")
                        if ts:
                            post_time = datetime.fromtimestamp(int(ts))
                            break
                        title = te.get_attribute("title") or te.text
                        if title:
                            post_time = self._parse_relative_time(title)
                            break

                    # Kiểm tra giới hạn ngày quét lùi lại
                    if post_time and post_time < cutoff_date:
                        continue

                    # 4. Trích xuất Link bài viết
                    post_url = ""
                    link_els = el.find_elements(By.CSS_SELECTOR, "a[href*='/posts/'], a[href*='story_fbid'], a[href*='/permalink/']")
                    if link_els:
                        post_url = link_els[0].get_attribute("href") or ""

                    # 5. Trích xuất các lượt tương tác (chỉ lấy số)
                    likes = comments = shares = 0
                    reaction_els = el.find_elements(By.CSS_SELECTOR, "[aria-label*='reaction'], span[aria-hidden]")
                    for re_el in reaction_els[:3]:
                        txt = re_el.text
                        if txt:
                            val = self._extract_reaction_count(txt)
                            if likes == 0: likes = val
                            elif comments == 0: comments = val
                            else: shares = val

                    post = FacebookPost(
                        post_id=post_id[:100],
                        group_name=self.driver.title.split("|")[0].strip(),
                        group_url=group_url,
                        author=author,
                        content=content.strip(),
                        post_url=post_url,
                        timestamp=post_time.isoformat() if post_time else datetime.now().isoformat(),
                        likes=likes,
                        comments=comments,
                        shares=shares,
                        keywords_matched=matched if isinstance(matched, list) else [],
                    )
                    collected.append(post)
                    logger.info(f"  📝 Thu thập: {author[:15]} - {content[:40]}...")

                    if len(collected) >= max_posts:
                        break

                except Exception as e:
                    logger.debug(f"Bỏ qua bài viết lỗi: {e}")
                    continue

            # Thực hiện cuộn xuống để Facebook tải tiếp bài viết
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
                last_height = new_height

        return collected

    def _keyword_match(self, text: str, keywords: List[str]) -> List[str]:
        """Kiểm tra văn bản có chứa từ khóa nào không (khớp chính xác từ)."""
        matched = []
        for kw in keywords:
            # Pattern đảm bảo kw đứng độc lập, không dính liền với chữ/số khác
            pattern = rf"(?i)(?<![\w\d]){re.escape(kw)}(?![\w\d])"
            if re.search(pattern, text):
                matched.append(kw)
        return matched

    def _parse_relative_time(self, time_str: str) -> datetime:
        """Chuyển đổi thời gian tương đối của Facebook (VD: 2 giờ trước) sang datetime."""
        now = datetime.now()
        time_str = time_str.lower()
        
        try:
            # Xử lý các bài viết vừa đăng
            if "giây" in time_str or "vừa" in time_str:
                return now
                
            num_match = re.search(r"(\d+)", time_str)
            if not num_match:
                return now
                
            num = int(num_match.group(1))
            
            if "giờ" in time_str:
                return now - timedelta(hours=num)
            elif "phút" in time_str:
                return now - timedelta(minutes=num)
            elif "ngày" in time_str:
                return now - timedelta(days=num)
        except:
            pass
        return now

    def _extract_reaction_count(self, text: str) -> int:
        """Trích xuất con số từ văn bản tương tác (VD: '12K' -> 12000)."""
        if not text: return 0
        match = re.search(r"(\d+\.?\d*)([KkMm]?)", text)
        if not match: return 0
        
        val = float(match.group(1))
        suffix = match.group(2).upper()
        
        if suffix == "K": val *= 1000
        elif suffix == "M": val *= 1000000
        return int(val)

    def close(self):
        """Đóng trình duyệt."""
        if self.driver:
            self.driver.quit()
