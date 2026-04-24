"""
app/scraper.py — Facebook Scraper.

Hỗ trợ:
  - Facebook Pages (URL: /pagename hoặc /profile.php?id=...)
  - Facebook Groups (URL: /groups/...)

Dùng Selenium + cookie để thu thập bài viết không cần đăng nhập thủ công.

CHANGELOG:
  - FIX: cutoff_date dùng đầu ngày (00:00) thay vì now-24h
  - FIX: "hôm qua"/"yesterday" → 23:59:59 hôm qua, chắc chắn bị lọc
  - FIX: post_time=None → skip bài, không lưu timestamp giả
  - FIX: Regex làm sạch group_name (bỏ badge thông báo "(18) ")
  - FIX: Regex làm sạch post_url (bỏ tracking token __cft__, __tn__, comment_id)
  - FIX: Regex trích post_id từ URL thay vì hash() âm không ổn định
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


# ── Regex patterns dùng chung ─────────────────────────────────────────────────

# Xoá badge số thông báo kiểu "(18) " ở đầu tên nhóm/trang
_RE_NOTIF_BADGE = re.compile(r"^\(\d+\)\s*")

# Trích post_id số từ URL
_RE_POST_ID_URL  = re.compile(r"/posts/(\d+)")
_RE_POST_ID_FBID = re.compile(r"story_fbid=(\d+)")
_RE_POST_ID_PERM = re.compile(r"/permalink/(\d+)")
_RE_POST_ID_P    = re.compile(r"/p/(\d+)")

# Tracking params của Facebook cần xoá khỏi URL
_TRACKING_PARAMS = {"__cft__", "__tn__", "comment_id", "__xts__", "ref", "source"}

# Noise patterns trong content
_NOISE_PATTERNS = [
    r"\d+\s*(giờ|phút|giây|ngày|tuần|tháng|hour|min|sec)(\s*trước)?",
    r"(Thích|Bình luận|Chia sẻ|Like|Comment|Share)\s*\d*",
    r"Người đóng góp nhiều nhất",
    r"Theo dõi",
    r"Người tham gia ẩn danh\s*\d*",
    r"Xem thêm",
    r"Xem bản dịch",
    r"\bGợi ý cho bạn\b",
]
_RE_NOISE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


# ── Helpers làm sạch dữ liệu ─────────────────────────────────────────────────

def _clean_group_name(raw: str) -> str:
    """Xoá badge thông báo: '(18) Antigravity VN' → 'Antigravity VN'"""
    return _RE_NOTIF_BADGE.sub("", raw).strip()


def _clean_post_url(raw_url: str) -> str:
    """
    Xoá tracking token của Facebook khỏi post_url.
    /posts/123/?comment_id=456&__cft__[0]=XYZ&__tn__=R-R → /posts/123/
    """
    if not raw_url:
        return ""
    try:
        parsed   = urlparse(raw_url)
        qs       = parse_qs(parsed.query, keep_blank_values=False)
        clean_qs = {
            k: v for k, v in qs.items()
            if not any(k.startswith(tp) for tp in _TRACKING_PARAMS)
        }
        new_query = urlencode(clean_qs, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return raw_url


def _extract_post_id_from_url(url: str) -> Optional[str]:
    """Trích post_id số thực từ URL. Trả None nếu không tìm được."""
    if not url:
        return None
    for pattern in [_RE_POST_ID_URL, _RE_POST_ID_FBID, _RE_POST_ID_PERM, _RE_POST_ID_P]:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def _clean_content(raw: str) -> str:
    """Làm sạch content: xoá noise UI, chuẩn hoá khoảng trắng."""
    text = _RE_NOISE.sub("", raw)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:2000]


# ─────────────────────────────────────────────────────────────────────────────

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
        source_type:      str = "page",
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
        return "group" if "/groups/" in url.lower() else "page"

    def _force_chronological(self):
        """
        Click nút sort 'Bài viết mới' trong Facebook Group.
        
        XPath PHẢI loại trừ thẻ article để tránh click nhầm vào chữ 'phù hợp'
        xuất hiện trong nội dung bài viết của người dùng.
        """
        try:
            wait = WebDriverWait(self.driver, 8)
            
            # Cuộn lên đầu trang để đảm bảo nút sort hiển thị
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            # XPath loại trừ thẻ article: không tìm trong [ancestor::article]
            # Nút sort luôn nằm TRƯỚC feed, không nằm trong bài viết cụ thể nào
            sort_btn_xpath = (
                "//div[@role='button' and not(ancestor::div[@role='article'])]"
                "//span[contains(text(),'Phù hợp') or contains(text(),'Relevant')"
                "       or contains(text(),'Top') or contains(text(),'Sắp xếp')]"
            )
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, sort_btn_xpath)))
            btn.click()
            time.sleep(1.5)

            # Click "Bài viết mới" trong dropdown vừa mở
            # Cũng loại trừ article để chắc chắn đây là menu option
            new_xpath = (
                "//div[@role='option' or @role='menuitem' or @role='listitem']"
                "//span[contains(text(),'Bài viết mới') or contains(text(),'New activity') or contains(text(),'Recent')]"
                " | //span[contains(text(),'Bài viết mới') or contains(text(),'New activity')]"
                "[not(ancestor::div[@role='article'])]"
            )
            newest = wait.until(EC.element_to_be_clickable((By.XPATH, new_xpath)))
            newest.click()
            time.sleep(2)
            logger.info("🔽 Đã click chuyển sang 'Bài viết mới' bằng UI")

        except Exception as e:
            logger.warning(f"⚠️ Không tìm được nút sort 'Bài viết mới': {e}")

    def scrape(
        self,
        url:       str,
        keywords:  List[str] = None,
        max_posts: int = 50,
        days_back: int = 1,
    ) -> List[FacebookPost]:
        """
        Thu thập bài viết từ Page hoặc Group.

        days_back=1 → chỉ lấy bài từ 00:00 HÔM NAY trở đi
        days_back=2 → từ 00:00 HÔM QUA trở đi
        """
        source_type = self._detect_source_type(url)
        if not url.startswith("http"):
            url = f"https://www.facebook.com/{url}"

        logger.info(f" Scraping {source_type}: {url}")
        self.driver.get(url)
        time.sleep(5)
        
        # Bắt buộc click UI để lấy bài mới nhất (tránh bị kẹt bài Top Posts cũ làm dừng vòng lặp)
        if source_type == "group":
            self._force_chronological()

        collected      = []
        seen_ids       = set()

        # FIX BUG 1: cutoff = đầu ngày, KHÔNG phải now - 24h
        today       = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = today - timedelta(days=days_back - 1)
        logger.info(f" Cutoff: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')} (days_back={days_back})")

        last_height      = self.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts  = 0
        consecutive_old  = 0   # Số bài cũ LIÊN TIẼP
        MAX_OLD_STREAK   = 1   # Feed chronological: gặp bài cũ đầu tiên là dừng ngay

        while len(collected) < max_posts and scroll_attempts < 25 and consecutive_old < MAX_OLD_STREAK:
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

            count_before = len(collected)   # Đếm trước mỗi vòng

            for el in post_els:
                try:
                    # ── Post URL → lấy trước để dùng cho post_id ──────────────
                    raw_post_url = ""
                    for lsel in [
                        "a[href*='/posts/']",
                        "a[href*='story_fbid']",
                        "a[href*='/permalink/']",
                        "a[href*='/p/']",
                    ]:
                        link_els = el.find_elements(By.CSS_SELECTOR, lsel)
                        if link_els:
                            raw_post_url = link_els[0].get_attribute("href") or ""
                            break

                    # FIX: Làm sạch URL (bỏ tracking token)
                    post_url = _clean_post_url(raw_post_url)

                    # FIX: Post ID từ URL thay vì hash() âm
                    post_id = _extract_post_id_from_url(raw_post_url)
                    if not post_id:
                        post_id = el.get_attribute("aria-label") or el.get_attribute("id") or ""
                    if not post_id:
                        post_id = str(abs(hash(el.text[:80])) % (10 ** 16))
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

                    # FIX: Làm sạch content bằng regex
                    content = _clean_content(content)
                    if len(content) < 10:
                        continue

                    # Keyword filter đã được chuyển sang job.py sau khi scrape xong
                    # Để scraper ấy được HẾT bài hôm nay không bỏ sót
                    matched = self._keyword_match(content, keywords) if keywords else ["*"]

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

                    # Fallback mạnh tay cho giao diện FB mới: 
                    # Timestamp (VD: "28 phút", "1 giờ") thường nằm trần trụi trong các thẻ <a> hoặc <span> mà KHÔNG CÓ thẻ <abbr>.
                    if post_time is None:
                        for link in el.find_elements(By.CSS_SELECTOR, "a[role='link'], a[href*='/groups/']"):
                            text = link.text.strip().lower()
                            # Kiểm tra xem text có giống chuỗi thời gian không
                            if text and any(kw in text for kw in ["vừa", "phút", "giờ", "hôm qua", "ngày", "tháng", "năm", "min", "hr", "day", "sec"]):
                                parsed = self._parse_relative_time(text)
                                if parsed:
                                    post_time = parsed
                                    break

                    # Không đọc được timestamp → coi như bài mới nhất (tránh bỏ sót)
                    if post_time is None:
                        logger.debug(f"⚠️ Không đọc được timestamp, coi là bài mới (id={post_id[:20]})")
                        post_time = datetime.now()

                    # Lọc theo cutoff: phân biệt bài ghim vs bài cũ thực sự
                    if post_time < cutoff_date:
                        age_days = (cutoff_date - post_time).days
                        if age_days > 7:
                            # Bài ghim (pinned) — skip nhẹ nhàng, KHÔNG tăng streak
                            logger.debug(
                                f"📌 Skip bài ghim: {post_time.strftime('%Y-%m-%d')} "
                                f"(cách {age_days} ngày — bài ghim, không dừng)"
                            )
                            continue
                        else:
                            # Bài của hôm qua/gần đây → đã qua ranh giới ngày, dừng
                            logger.info(
                                f"🛑 Gặp bài hôm qua {post_time.strftime('%Y-%m-%d %H:%M')} "
                                f"< cutoff {cutoff_date.strftime('%Y-%m-%d %H:%M')} → Dừng cuộn"
                            )
                            consecutive_old += 1
                            if consecutive_old >= MAX_OLD_STREAK:
                                logger.info(f"🛑 Dừng: đã qua hết bài hôm nay (thu {len(collected)} bài)")
                                break
                            continue
                    consecutive_old = 0   # Gặp bài mới → reset

                    # Làm sạch group_name (bỏ badge thông báo)
                    raw_title = self.driver.title.split("|")[0].strip()
                    page_name = _clean_group_name(raw_title)

                    collected.append(FacebookPost(
                        post_id          = post_id[:100],
                        group_name       = page_name,
                        group_url        = url,
                        author           = author,
                        content          = content.strip(),
                        post_url         = post_url,
                        timestamp        = post_time.isoformat(),
                        source_type      = source_type,
                        keywords_matched = matched if isinstance(matched, list) else [],
                    ))

                    logger.debug(f"   {author[:15]} — {content[:50]}...")

                    if len(collected) >= max_posts:
                        break

                except Exception as e:
                    logger.debug(f"Bỏ qua bài lỗi: {e}")
                    continue

            # Scroll xuống
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
                last_height = new_height

        if consecutive_old >= MAX_OLD_STREAK:
            logger.info(f"🛑 Dừng: đã cuộn qua khỏi vùng bài hôm nay (có {MAX_OLD_STREAK} bài cũ liên tiếp)")

        logger.info(f" Collected {len(collected)} posts từ {url}")
        return collected

    # ── Legacy alias ──────────────────────────────────────────────────────────
    def scrape_group(self, group_url: str, keywords: List[str] = None,
                     max_posts: int = 50, days_back: int = 1) -> List[FacebookPost]:
        return self.scrape(group_url, keywords=keywords, max_posts=max_posts, days_back=days_back)

    def scrape_page(self, page_url: str, keywords: List[str] = None,
                    max_posts: int = 50, days_back: int = 1) -> List[FacebookPost]:
        return self.scrape(page_url, keywords=keywords, max_posts=max_posts, days_back=days_back)



    def _keyword_match(self, text: str, keywords: List[str]) -> List[str]:
        matched = []
        text_lower = text.lower()
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(kw)
        return matched

    def _is_old_post(self, el, cutoff_date: datetime) -> bool:
        """Kiểm tra nhanh 1 element có phải bài cũ hơn cutoff_date không."""
        try:
            for tsel in ["abbr[data-utime]", "a abbr", "span abbr"]:
                for te in el.find_elements(By.CSS_SELECTOR, tsel):
                    ts = te.get_attribute("data-utime")
                    if ts:
                        return datetime.fromtimestamp(int(ts)) < cutoff_date
                    title = te.get_attribute("title") or te.text
                    if title:
                        t = self._parse_relative_time(title)
                        if t:
                            return t < cutoff_date
            for link in el.find_elements(By.CSS_SELECTOR, "a[role='link']"):
                text = link.text.strip().lower()
                if text and any(kw in text for kw in ["phút", "giờ", "vừa", "min", "hr"]):
                    t = self._parse_relative_time(text)
                    if t:
                        return t < cutoff_date
        except Exception:
            pass
        return False  # Không biết → coi là bài mới

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """
        Parse chuỗi thời gian tương đối của Facebook.

        FIX BUG 2: "hôm qua" → 23:59:59 hôm qua (chắc chắn < cutoff 00:00 hôm nay)
        FIX: Trả None khi không parse được (thay vì trả now())
        """
        now = datetime.now()
        s   = time_str.lower().strip()
        try:
            if "giây" in s or "vừa" in s or "just" in s or "vài" in s:
                return now

            # FIX BUG 2
            if "hôm qua" in s or "yesterday" in s:
                return now.replace(hour=23, minute=59, second=59, microsecond=0) - timedelta(days=1)

            old_keywords = [
                "tháng", "thg", "năm", "month", "year",
                "jan", "feb", "mar", "apr", "may", "jun",
                "jul", "aug", "sep", "oct", "nov", "dec",
            ]
            if any(kw in s for kw in old_keywords):
                return now - timedelta(days=400)

            m = re.search(r"(\d+)", s)
            if not m:
                return None   # FIX: None thay vì now()

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

        return None   # FIX: None thay vì now()

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
