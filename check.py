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

def extract
