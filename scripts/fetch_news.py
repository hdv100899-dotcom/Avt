#!/usr/bin/env python3
"""
Thu thập tin tức mới nhất về Biển Đông và các thực thể (đảo, đá, bãi...).

- Nguồn: Google News RSS (tiếng Việt + tiếng Anh) và RSS mục Thế giới của một số báo Việt Nam.
- Chỉ giữ bài có nhắc tới từ khóa Biển Đông hoặc tên một thực thể trong js/data.js.
- Gộp với data/news.json hiện có, giữ tối đa MAX_ITEMS bài trong KEEP_DAYS ngày gần nhất.
- Chỉ dùng thư viện chuẩn Python → chạy được ngay trên GitHub Actions.

Chạy: python3 scripts/fetch_news.py
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JS = os.path.join(ROOT, "js", "data.js")
OUT = os.path.join(ROOT, "data", "news.json")
KEEP_DAYS = 45
MAX_ITEMS = 800
UA = "Mozilla/5.0 (compatible; BienDongMonitor/1.0; +https://github.com)"

GN_VI = "https://news.google.com/rss/search?q={q}&hl=vi&gl=VN&ceid=VN:vi"
GN_EN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

QUERIES_VI = [
    '"Biển Đông" when:7d',
    '"Trường Sa" when:7d',
    '"Hoàng Sa" when:7d',
    '"bãi Tư Chính" OR "nhà giàn DK1" when:14d',
    '"đá Chữ Thập" OR "đá Vành Khăn" OR "đá Xu Bi" OR "Gạc Ma" when:14d',
    '"bãi Cỏ Mây" OR "Scarborough" OR "Ba Bình" when:14d',
    '"cảnh sát biển Việt Nam" OR "hải quân Việt Nam" Biển Đông when:7d',
]
QUERIES_EN = [
    '"South China Sea" when:7d',
    '"Spratly" when:7d',
    '"Paracel" when:7d',
    '"Second Thomas Shoal" OR "Ayungin" when:7d',
    '"Scarborough Shoal" when:7d',
    '"Mischief Reef" OR "Fiery Cross" OR "Subi Reef" when:14d',
    '"Sabina Shoal" OR "Whitsun Reef" OR "Thitu" OR "Pag-asa Island" when:14d',
    '"Vanguard Bank" OR "Woody Island" OR "Triton Island" when:14d',
]
EXTRA_FEEDS = [
    ("VnExpress", "https://vnexpress.net/rss/the-gioi.rss", "vi"),
    ("VnExpress", "https://vnexpress.net/rss/thoi-su.rss", "vi"),
    ("Tuổi Trẻ", "https://tuoitre.vn/rss/the-gioi.rss", "vi"),
    ("Tuổi Trẻ", "https://tuoitre.vn/rss/thoi-su.rss", "vi"),
    ("Thanh Niên", "https://thanhnien.vn/rss/the-gioi.rss", "vi"),
    ("Thanh Niên", "https://thanhnien.vn/rss/thoi-su.rss", "vi"),
]
GENERAL_TERMS = [
    "Biển Đông", "Trường Sa", "Hoàng Sa", "South China Sea", "Spratly", "Paracel",
    "West Philippine Sea", "南海", "南沙", "西沙", "đường lưỡi bò", "nine-dash line",
]
# Tin thời tiết / thiên tai chỉ nhắc "Biển Đông" như vùng biển → loại bỏ
NOISE = re.compile(r"thời tiết|\bbão\b|siêu bão|áp thấp|không khí lạnh|gió mùa|mưa lớn|mưa diện rộng|sóng lớn|"
                   r"earthquake|typhoon|tropical storm|tropical depression|weather|magnitude", re.I)
AMBIGUOUS = {"Rizal", "Parola", "Spratly Island", "Đảo Cây", "Tree Island", "Money Island", "Flat Island"}
TYPE_PREFIX = re.compile(r"^(Đảo|Đá|Bãi cạn|Bãi|Cồn san hô|Cồn|Nhà giàn)\s+", re.I)


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def load_terms():
    """Lấy tên thực thể (Việt/Anh/Trung) trong js/data.js để làm từ khóa lọc."""
    terms = set(GENERAL_TERMS)
    try:
        src = open(DATA_JS, encoding="utf-8").read()
        src = src[src.find("DEFAULT_FEATURES"):]  # chỉ lấy phần danh sách thực thể
    except OSError:
        return sorted(terms)
    for key in ("name", "nameEn", "nameCn"):
        for v in re.findall(r'\b%s:\s*"([^"]+)"' % key, src):
            v = nfc(v)
            for part in re.split(r"[()/–]", v):
                part = part.strip()
                if not part:
                    continue
                terms.add(part)
                short = TYPE_PREFIX.sub("", part)
                if short != part and len(short.split()) >= 2:
                    terms.add(short)
    # bỏ các từ quá chung chung / dễ trùng
    terms -= AMBIGUOUS
    return sorted(t for t in terms if len(t) >= 4 or re.search(r"[\u4e00-\u9fff]", t))


def build_matcher(terms):
    cjk = [t for t in terms if re.search(r"[\u4e00-\u9fff]", t)]
    latin = [t for t in terms if t not in cjk]
    # "Đá Lớn", "Đá Nam"... (tiền tố + 1 từ) dễ trùng cụm từ thường → so khớp phân biệt hoa/thường
    strict = [t for t in latin if TYPE_PREFIX.match(t) and len(t.split()) == 2]
    loose = [t for t in latin if t not in strict]
    alt = lambda ts: "|".join(re.escape(t) for t in sorted(ts, key=len, reverse=True)) or "(?!)"
    pat_i = re.compile(r"(?<!\w)(" + alt(loose) + r")(?!\w)", re.I)
    pat_s = re.compile(r"(?<!\w)(" + alt(strict) + r")(?!\w)")

    def match(text):
        text = nfc(text)
        return bool(pat_i.search(text) or pat_s.search(text)) or any(t in text for t in cjk)

    return match


def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            print(f"  ! lỗi {e} ({url[:90]})", file=sys.stderr)
            time.sleep(2 * (i + 1))
    return None


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_date(s):
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2}) ?(AM|PM)?", s, re.I)
    if m:  # Tuổi Trẻ: "10/31/2026 6:54:00 PM" (giờ Việt Nam)
        mo, dd, yy, hh, mi, ss, ap = m.groups()
        hh = int(hh) % 12 + (12 if (ap or "").upper() == "PM" else 0) if ap else int(hh)
        d = datetime(int(yy), int(mo), int(dd), hh, int(mi), int(ss), tzinfo=timezone(timedelta(hours=7)))
        return d.astimezone(timezone.utc)
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def parse_feed(raw, default_source, lang, origin):
    out = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  ! XML lỗi: {e}", file=sys.stderr)
        return out
    for it in root.iter("item"):
        title = nfc(strip_html(it.findtext("title")))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        src_el = it.find("source")
        source = nfc(src_el.text.strip()) if src_el is not None and src_el.text else default_source
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        summary = nfc(strip_html(it.findtext("description")))
        if summary.startswith(title):
            summary = summary[len(title):].strip(" -–")
        if source and summary.endswith(source):
            summary = summary[: -len(source)].strip(" -–\u00a0")
        out.append({
            "title": title,
            "link": link,
            "source": source,
            "published": parse_date(it.findtext("pubDate")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": summary[:400],
            "lang": lang,
            "origin": origin,
        })
    return out


def key_of(a):
    t = re.sub(r"\W+", "", a["title"].lower())
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def main():
    match = build_matcher(load_terms())
    collected = []
    for q in QUERIES_VI:
        print("VI:", q)
        raw = fetch(GN_VI.format(q=urllib.parse.quote_plus(q)))
        if raw:
            collected += parse_feed(raw, "Google News", "vi", "google-vi")
        time.sleep(1.5)
    for q in QUERIES_EN:
        print("EN:", q)
        raw = fetch(GN_EN.format(q=urllib.parse.quote_plus(q)))
        if raw:
            collected += parse_feed(raw, "Google News", "en", "google-en")
        time.sleep(1.5)
    for name, url, lang in EXTRA_FEEDS:
        print("RSS:", url)
        raw = fetch(url)
        if raw:
            collected += parse_feed(raw, name, lang, "rss")

    fresh = [a for a in collected if match(a["title"] + " " + a["summary"]) and not NOISE.search(a["title"])]
    print(f"Thu được {len(collected)} bài, liên quan: {len(fresh)}")

    old = []
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8")).get("articles", [])
        except Exception:  # noqa: BLE001
            old = []
    items = {}
    old = [a for a in old if not NOISE.search(a.get("title", ""))]
    for a in old + fresh:  # bài mới ghi đè bài cũ cùng tiêu đề
        a["id"] = key_of(a)
        if a["id"] in items:
            a.setdefault("firstSeen", items[a["id"]].get("firstSeen"))
        a.setdefault("firstSeen", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        items[a["id"]] = a
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    arts = sorted((a for a in items.values() if a["published"] >= cutoff), key=lambda a: a["published"], reverse=True)[:MAX_ITEMS]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(arts),
            "articles": arts,
        }, f, ensure_ascii=False, indent=1)
    print(f"Đã ghi {len(arts)} bài vào {OUT}")


if __name__ == "__main__":
    main()
