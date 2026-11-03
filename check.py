import os
import re
import json
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# =====================================
# TELEGRAM SETTINGS
# =====================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

STATE_FILE = "showtimes_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"
}

# =====================================
# MOVIES TO MONITOR (تجربة حية على فيلم Clayface)
# =====================================

TARGETS = [
    {
        "movie": "Clayface",
        "hall": "STANDARD",
        "url": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=clayface",
        "fallback_query": "site:egy.voxcinemas.com/showtimes city-centre-almaza clayface"
    }
]

# =====================================
# DETECTION PATTERNS
# =====================================

DATE_PATTERN = re.compile(
    r"\b(?:"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*,?\s*"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r")\b",
    re.I
)

TIME_PATTERN = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?\b"
    r"|\b(?:1[0-2]|0?[1-9])\s*(?:am|pm)\b",
    re.I
)

BOOKING_PATTERN = re.compile(
    r"\b(book now|book tickets|select seats|choose seats|"
    r"book|tickets|select)\b",
    re.I
)

# =====================================
# TELEGRAM NOTIFICATIONS
# =====================================

def send_telegram(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    try:
        response = session.post(url, json=payload, timeout=20)
        response.raise_for_status()

        if response.json().get("ok"):
            print("✅ Telegram notification sent.")
            return True

        print("❌ Telegram rejected the message.")
        return False

    except requests.RequestException as error:
        print(f"❌ Telegram error: {error}")
        return False


# =====================================
# EXTRACT ACTUAL SHOWTIME CANDIDATES
# =====================================

def extract_showtimes(html, target):
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    candidates = soup.find_all(["div", "li", "article", "section"])
    candidates.sort(key=lambda tag: len(tag.get_text(" ", strip=True)))

    found = {}

    for tag in candidates:
        text = tag.get_text(" ", strip=True)

        if not text or len(text) > 1800:
            continue

        dates = DATE_PATTERN.findall(text)
        times = TIME_PATTERN.findall(text)

        if not dates or not times:
            continue

        booking_links = []
        for link in tag.find_all("a", href=True):
            href = urljoin(target["url"], link["href"])
            label = link.get_text(" ", strip=True)

            if (
                BOOKING_PATTERN.search(label)
                or "book" in href.lower()
                or "seat" in href.lower()
            ):
                booking_links.append(href)

        date_value = dates[0].strip()
        time_value = times[0].strip()
        booking_link = booking_links[0] if booking_links else target["url"]

        unique_text = f"{target['movie']}|{target['hall']}|{date_value}|{time_value}"
        showtime_id = hashlib.sha256(unique_text.lower().encode("utf-8")).hexdigest()

        found[showtime_id] = {
            "movie": target["movie"],
            "hall": target["hall"],
            "date": date_value,
            "time": time_value,
            "link": booking_link
        }

    return found


# =====================================
# CHECK TARGET (WITH FALLBACK)
# =====================================

def check_target(session, target):
    print(f"\n⏳ Checking {target['movie']} ({target['hall']})...")
    html = ""
    success = False

    try:
        response = session.get(target["url"], timeout=15)
        if response.status_code == 200 and len(response.text) > 500:
            html = response.text
            success = True
            print("🎯 Direct fetch successful.")
    except Exception:
        print("⚠️ Direct fetch blocked/timeout, switching to smart search fallback...")

    if not success:
        try:
            search_url = f"https://html.duckduckgo.com/html/?q={target['fallback_query']}"
            response = session.get(search_url, timeout=15)
            if response.status_code in (200, 202) and len(response.text) > 300:
                html = response.text
                success = True
                print("🔍 Fallback search fetch successful.")
            else:
                print(f"❌ Search fallback returned HTTP {response.status_code}")
        except requests.RequestException as error:
            print(f"❌ Connection error on fallback: {error}")
            return None

    if not success or len(html) < 200:
        print("⚠️ Invalid or empty page content.")
        return None

    showtimes = extract_showtimes(html, target)
    print(f"🎯 Found {len(showtimes)} potential showtimes.")
    return showtimes


# =====================================
# MAIN MONITORING SYSTEM
# =====================================

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Missing Telegram credentials.")
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    # رسالة بدء التجربة
    send_telegram(
        session,
        "🤖 **بدء اختبار استخراج المواعيد المتاحة لفيلم (Clayface)...**"
    )

    for target in TARGETS:
        showtimes = check_target(session, target)

        if not showtimes:
            print(f"⏳ No showtimes extracted for {target['movie']}. Check page structure or patterns.")
            continue

        print(f"\n📋 المواعيد المتاحة للفيلم {target['movie']}:")
        for sid, item in showtimes.items():
            print(f" - 📅 {item['date']} | 🕒 {item['time']} | 🔗 {item['link']}")

        items_list = list(showtimes.values())[:5]
        message = (
            "🍿 **اختبار المواعيد المتاحة حالياً!** 🍿\n\n"
            f"🎬 Movie: {target['movie']}\n"
            f"🏛️ Cinema: City Centre Almaza\n\n"
        )
        for item in items_list:
            message += f"📅 {item['date']} at 🕒 {item['time']}\n🎟️ {item['link']}\n\n"

        send_telegram(session, message)
        time.sleep(2)

    session.close()
    print("\n✅ Test completed.")


if __name__ == "__main__":
    main()
            
