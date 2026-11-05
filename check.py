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

STATE_FILE = "all_movies_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"
}

MOVIES_URL = "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza"
FALLBACK_QUERY = "site:egy.voxcinemas.com city-centre-almaza showtimes"

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
# LOAD AND SAVE STATE
# =====================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        print("⚠️ Could not read saved state.")
        return {}

def save_state(state):
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, STATE_FILE)

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
# EXTRACT ALL SHOWTIMES
# =====================================

def extract_all_showtimes(html):
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    candidates = soup.find_all(["div", "li", "article", "section"])
    candidates.sort(key=lambda tag: len(tag.get_text(" ", strip=True)))

    found = {}

    for tag in candidates:
        text = tag.get_text(" ", strip=True)

        if not text or len(text) > 2000:
            continue

        dates = DATE_PATTERN.findall(text)
        times = TIME_PATTERN.findall(text)

        if not dates or not times:
            continue

        booking_links = []
        for link in tag.find_all("a", href=True):
            href = urljoin(MOVIES_URL, link["href"])
            label = link.get_text(" ", strip=True)

            if (
                BOOKING_PATTERN.search(label)
                or "book" in href.lower()
                or "seat" in href.lower()
                or "showtimes" in href.lower()
            ):
                booking_links.append(href)

        if not BOOKING_PATTERN.search(text) and not booking_links:
            continue

        movie_name = "Unknown Movie"
        heading = tag.find(["h1", "h2", "h3", "h4", "strong"])
        if heading:
            movie_name = heading.get_text(" ", strip=True)
        else:
            lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 3]
            if lines:
                movie_name = lines[0]

        if len(movie_name) > 60:
            movie_name = movie_name[:60] + "..."

        date_value = dates[0].strip()
        time_value = times[0].strip()
        booking_link = booking_links[0] if booking_links else MOVIES_URL

        hall_type = "Standard"
        if re.search(r"\bIMAX\b", text, re.I):
            hall_type = "IMAX"
        elif re.search(r"\bMAX\b", text, re.I):
            hall_type = "MAX"
        elif re.search(r"\bGOLD\b", text, re.I):
            hall_type = "GOLD"

        unique_text = f"{movie_name}|{hall_type}|{date_value}|{time_value}"
        showtime_id = hashlib.sha256(unique_text.lower().encode("utf-8")).hexdigest()

        found[showtime_id] = {
            "movie": movie_name,
            "hall": hall_type,
            "date": date_value,
            "time": time_value,
            "link": booking_link
        }

    return found

# =====================================
# FETCH MOVIES PAGE
# =====================================

def fetch_movies(session):
    html = ""
    success = False

    try:
        response = session.get(MOVIES_URL, timeout=15)
        if response.status_code == 200 and len(response.text) > 500:
            html = response.text
            success = True
            print("🎯 Direct fetch successful.")
    except Exception:
        print("⚠️ Direct fetch blocked/timeout, switching to smart search fallback...")

    if not success:
        try:
            search_url = f"https://html.duckduckgo.com/html/?q={FALLBACK_QUERY}"
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

    return extract_all_showtimes(html)

# =====================================
# MAIN
# =====================================

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:

        
