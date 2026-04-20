"""
app/scraper.py — Facebook Scraper.

Hỗ trợ:
  - Facebook Pages (URL: /pagename hoặc /profile.php?id=...)
  - Facebook Groups (URL: /groups/...)

Dùng Selenium + cookie để thu thập bài viết không cần đăng nhập thủ công.
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
        post_id:          str,
        group_name:       str,
        group_url:        str,
        author:           str,
        content:          str,
        post_url:         str,
        timestamp:        str,
        source_type:      str = "page",   # "page" hoặc "group"
        likes:            int = 0,
        comments:         int = 0,
        shares:           int = 0,
        keywords_matched: List[str] = None,
    ):
        self.post_id          = post_id
        self.group_name       = group_name
        self.group_url        = group_url
        self.author           = author
        self.content          = content
        self.post_url         = post_url
        self.timestamp        = timestamp
        self.source_type      = source_type
        self.likes            = likes
        self.comments         = comments
        self.shares           = shares
        self.keywords_matched = keywords_matched or []

    def to_dict(self):
        return self.__dict__


class FacebookScraper:
    """Scraper hỗ trợ cả Pages và Groups."""

    def __init__(self, cookie_string: str, headless: bool = True):
        self.cookie_string = cookie_string
        self.headless      = headless
        self.driver        = self._init_driver()
        self._set_cookies()

    def _init_driver(self):
        opts = Options()
        if self.headless:
            opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)

    def _set_cookies(self):
        try:
            self.driver.get("https://www.facebook.com")
            time.sleep(2)
            for part in self.cookie_string.split(";"):
                if "=" in part:
                    name, value = part.strip().split("=", 1)
                    try:
                        self.driver.add_cookie({
                            "name": name.strip(),
                            "value": value.strip(),
                            "domain": ".facebook.com",
                        })
                    except Exception:
                        pass
            logger.info("✅ Cookie đã được thiết lập")
            self.driver.refresh()
            time.sleep(3)
        except Exception as e:
            logger.error(f"❌ Lỗi cookie: {e}")

    @staticmethod
    def _detect_source_type(url: str) -> str:
        """Phân loại URL: 'group' hay 'page'."""
        url_lower = url.lower()
        if "/groups/" in url_lower:
            return "group"
        return "page"

    def scrape(
        self,
        url:       str,
        keywords:  List[str] = None,
        max_posts: int = 50,
        days_back: int = 1,
    ) -> List[FacebookPost]:
        """
        Thu thập bài viết từ một Page hoặc Group.
        Tự động nhận dạng loại URL.
        """
        source_type = self._detect_source_type(url)
        if not url.startswith("http"):
            url = f"https://www.facebook.com/{url}"

        logger.info(f"🌐 Scraping {source_type}: {url}")
        self.driver.get(url)
        time.sleep(5)

        collected    = []
        seen_ids     = set()
        cutoff_date  = datetime.now() - timedelta(days=days_back)
        last_height  = self.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0

        while len(collected) < max_posts and scroll_attempts < 25:
            # Selector bao phủ cả page lẫn group
            selectors = [
                'div[role="feed"] > div',
                'div[role="article"]',
                'div[data-pagelet*="FeedUnit"]',
            ]
            post_els = []
            for sel in selectors:
                post_els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if post_els:
                    break

            for el in post_els:
                try:
                    # ── Post ID ────────────────────────────────────────────────
                    post_id = el.get_attribute("aria-label") or el.get_attribute("id") or ""
                    if not post_id:
                        post_id = str(hash(el.text[:60]))
                    if post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    # ── Author ─────────────────────────────────────────────────
                    author = "Ẩn danh"
                    for sel in ["h2 strong", "h3 strong", "a[role='link'] strong", "strong"]:
                        els = el.find_elements(By.CSS_SELECTOR, sel)
                        if els:
                            author = els[0].text.strip()
                            break

                    # ── Content ────────────────────────────────────────────────
                    content = ""
                    content_sels = [
                        'div[data-ad-comet-preview="message"]',
                        'div[dir="auto"]',
                        'div.xdj266r',
                    ]
                    for csel in content_sels:
                        parts = el.find_elements(By.CSS_SELECTOR, csel)
                        if parts:
                            content = " ".join(p.text.strip() for p in parts if len(p.text.strip()) > 5)
                            if content:
                                break
                    if not content:
                        content = el.text

                    # Làm sạch noise
                    for pattern in [
                        r"\d+\s*(giờ|phút|giây|ngày|tuần|tháng|hour|min|sec)(\s*trước)?",
                        r"(Thích|Bình luận|Chia sẻ|Like|Comment|Share)\s*\d*",
                        r"Người đóng góp nhiều nhất",
                        r"Theo dõi",
                        r"Người tham gia ẩn danh\s*\d*",
                        r"Xem thêm",
                    ]:
                        content = re.sub(pattern, "", content, flags=re.IGNORECASE)
                    content = re.sub(r"\n{3,}", "\n\n", content).strip()
                    content = content[:2000]

                    if len(content) < 10:
                        continue

                    # ── Keyword filter ─────────────────────────────────────────
                    matched = self._keyword_match(content, keywords) if keywords else ["*"]
                    if keywords and not matched:
                        continue

                    # ── Timestamp ──────────────────────────────────────────────
                    post_time = None
                    time_sels = [
                        "a[href*='/posts/'] abbr",
                        "abbr[data-utime]",
                        "a abbr",
                        "span abbr",
                    ]
                    for tsel in time_sels:
                        for te in el.find_elements(By.CSS_SELECTOR, tsel):
                            ts = te.get_attribute("data-utime")
                            if ts:
                                post_time = datetime.fromtimestamp(int(ts))
                                break
                            title = te.get_attribute("title") or te.text
                            if title:
                                post_time = self._parse_relative_time(title)
                                break
                        if post_time:
                            break

                    if post_time and post_time < cutoff_date:
                        continue

                    # ── Post URL ───────────────────────────────────────────────
                    post_url = ""
                    for lsel in [
                        "a[href*='/posts/']",
                        "a[href*='story_fbid']",
                        "a[href*='/permalink/']",
                        "a[href*='/p/']",
                    ]:
                        link_els = el.find_elements(By.CSS_SELECTOR, lsel)
                        if link_els:
                            post_url = link_els[0].get_attribute("href") or ""
                            break

                    # ── Name / page title ──────────────────────────────────────
                    page_name = self.driver.title.split("|")[0].strip()

                    collected.append(FacebookPost(
                        post_id          = post_id[:100],
                        group_name       = page_name,
                        group_url        = url,
                        author           = author,
                        content          = content.strip(),
                        post_url         = post_url,
                        timestamp        = post_time.isoformat() if post_time else datetime.now().isoformat(),
                        source_type      = source_type,
                        keywords_matched = matched if isinstance(matched, list) else [],
                    ))

                    logger.debug(f"  📝 {author[:15]} — {content[:50]}...")

                    if len(collected) >= max_posts:
                        break

                except Exception as e:
                    logger.debug(f"Bỏ qua bài lỗi: {e}")
                    continue

            # Scroll xuống để tải thêm
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
                last_height = new_height

        logger.info(f"✅ Collected {len(collected)} posts từ {url}")
        return collected

    # ── Legacy alias ──────────────────────────────────────────────────────────
    def scrape_group(self, group_url: str, keywords: List[str] = None,
                     max_posts: int = 50, days_back: int = 1) -> List[FacebookPost]:
        """Backward-compatible wrapper — gọi self.scrape()."""
        return self.scrape(group_url, keywords=keywords, max_posts=max_posts, days_back=days_back)

    def scrape_page(self, page_url: str, keywords: List[str] = None,
                    max_posts: int = 50, days_back: int = 1) -> List[FacebookPost]:
        """Wrapper cho Facebook Pages."""
        return self.scrape(page_url, keywords=keywords, max_posts=max_posts, days_back=days_back)

    def _keyword_match(self, text: str, keywords: List[str]) -> List[str]:
        matched = []
        for kw in keywords:
            pattern = rf"(?i)(?<![a-zA-Z]){re.escape(kw)}(?![a-zA-Z])"
            if re.search(pattern, text):
                matched.append(kw)
        return matched

    def _parse_relative_time(self, time_str: str) -> datetime:
        now = datetime.now()
        s   = time_str.lower()
        try:
            # 1. Xử lý "vừa xong", "giây"
            if "giây" in s or "vừa" in s or "just" in s or "vài" in s:
                return now
            
            # 2. Xử lý "hôm qua" / "yesterday"
            if "hôm qua" in s or "yesterday" in s:
                return now - timedelta(days=1)

            # 3. Xử lý bài viết cũ (Tháng/Năm) - Cả tiếng Việt và tiếng Anh
            old_keywords = [
                "tháng", "thg", "năm", "month", "year", "yesterday",
                "jan", "feb", "mar", "apr", "may", "jun", 
                "jul", "aug", "sep", "oct", "nov", "dec"
            ]
            if any(kw in s for kw in old_keywords):
                # Nếu chứa từ khóa chỉ mốc thời gian cũ, trả về mốc > 30 ngày trước để bộ lọc loại bỏ
                return now - timedelta(days=32)

            # 4. Tìm con số đi kèm (ví dụ: "5 giờ", "2 ngày")
            m = re.search(r"(\d+)", s)
            if not m:
                return now
                
            n = int(m.group(1))
            if "giờ" in s or "hour" in s or "hr" in s:
                return now - timedelta(hours=n)
            if "phút" in s or "min" in s:
                return now - timedelta(minutes=n)
            if "ngày" in s or "day" in s:
                return now - timedelta(days=n)
            if "tuần" in s or "week" in s:
                return now - timedelta(weeks=n)
                
        except Exception:
            pass
            
        return now



    def _extract_reaction_count(self, text: str) -> int:
        if not text:
            return 0
        m = re.search(r"(\d+\.?\d*)([KkMm]?)", text)
        if not m:
            return 0
        val    = float(m.group(1))
        suffix = m.group(2).upper()
        if suffix == "K": val *= 1000
        if suffix == "M": val *= 1000000
        return int(val)

    def close(self):
        if self.driver:
            self.driver.quit()
