#!/usr/init/env python3
"""
Vox Cinemas showtime monitor - City Centre Almaza.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# =====================================
# SETTINGS
# =====================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

STATE_FILE = os.getenv("STATE_FILE", "showtimes_state.json")
LOG_FILE = os.getenv("LOG_FILE", "showtimes.log")
DEBUG_DIR = "debug"

CINEMA_NAME = "Vox City Centre Almaza"
DDG_URL = "https://html.duckduckgo.com/html/"

REQUEST_TIMEOUT = 15
RETRIES = 2
MAX_BLOCK_CHARS = 2500

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

# =====================================
# MOVIES TO MONITOR
# =====================================

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "keyword": "dune",
        "hall": "IMAX",
        "url": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three",
        "fallback_query": "site:egy.voxcinemas.com/showtimes city-centre-almaza dune imax schedule",
    },
    {
        "movie": "Avengers: Doomsday",
        "keyword": "avengers",
        "hall": "MAX",
        "url": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=avengers-doomsday-infinity-vision",
        "fallback_query": "site:egy.voxcinemas.com/showtimes city-centre-almaza avengers max schedule",
    },
]

# =====================================
# PATTERNS
# =====================================

MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"

DATE_PATTERN = re.compile(
    r"\b(?:"
    + r"\d{4}-\d{1,2}-\d{1,2}|"
    + r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    + WEEKDAY + r"\.?\s*,?\s*" + MONTH + r"\.?\s+\d{1,2}|"
    + MONTH + r"\.?\s+\d{1,2}|"
    + r"\d{1,2}\s+" + MONTH
    + r")\b",
    re.I,
)

TIME_PATTERN = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?\b"
    r"|\b(?:1[0-2]|0?[1-9])\s*(?:am|pm)\b",
    re.I,
)

HALL_PATTERN = re.compile(r"\b(IMAX|MAX|STANDARD|4DX|GOLD|LUXE|VIP|ATMOS)\b", re.I)

BOOKING_PATTERN = re.compile(
    r"\b(book now|book tickets|buy tickets|select seats|choose seats|book|buy|tickets|select)\b",
    re.I,
)

log = logging.getLogger("vox")


class FetchError(Exception):
    pass


# =====================================
# NETWORK
# =====================================

def fetch(session, url, params=None):
    last_error = "unknown error"

    for attempt in range(RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            # تم تعديل القبول ليشمل حالة 202 الخاصة بالبحث البديل ومعالجة الـ HTML
            if response.status_code in (200, 202) and len(response.text) > 300:
                return response.text
            last_error = f"HTTP {response.status_code}, {len(response.text)} chars"
        except requests.RequestException as error:
            last_error = str(error)

        if attempt < RETRIES:
            time.sleep(3 * (attempt + 1))

    raise FetchError(last_error)


def send_telegram(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "disable_web_page_preview": True}

    for _ in range(3):
        try:
            response = session.post(url, json=payload, timeout=20)

            if response.status_code == 429:
                retry_after = 5
                try:
                    retry_after = response.json().get("parameters", {}).get("retry_after", 5)
                except ValueError:
                    pass
                log.warning("Telegram rate limit hit. Waiting %s seconds.", retry_after)
                time.sleep(retry_after)
                continue

            if response.status_code == 200 and response.json().get("ok"):
                return True

            log.error("Telegram rejected the message: %s", response.text[:300])
            return False

        except (requests.RequestException, ValueError) as error:
            log.error("Telegram request failed: %s", error)
            time.sleep(3)

    return False


# =====================================
# STATE
# =====================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"notified": {}}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        log.warning("Could not read %s (%s). Starting with an empty state.", STATE_FILE, error)
        return {"notified": {}}

    if "notified" not in data:
        notified = {}
        for value in data.values():
            if isinstance(value, dict):
                notified.update(value)
        data = {"notified": notified}

    return data


def save_state(state):
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, STATE_FILE)


# =====================================
# PARSING
# =====================================

def find_booking_link(block, base_url):
    for link in block.find_all("a", href=True):
        href = urljoin(base_url, link["href"])
        label = link.get_text(" ", strip=True)
        if BOOKING_PATTERN.search(label) or "book" in href.lower() or "seat" in href.lower():
            return href
    return base_url


def next_hall_after(events, index):
    for _, kind, value in events[index + 1:]:
        if kind == "date":
            break
        if kind == "hall":
            return value
    return None


def parse_block(text, target):
    events = []
    for match in DATE_PATTERN.finditer(text):
        events.append((match.start(), "date", " ".join(match.group().split())))
    for match in HALL_PATTERN.finditer(text):
        events.append((match.start(), "hall", match.group().upper()))
    for match in TIME_PATTERN.finditer(text):
        events.append((match.start(), "time", " ".join(match.group().split())))
    events.sort(key=lambda event: event[0])

    halls_here = {value for _, kind, value in events if kind == "hall"}
    if target["hall"] not in halls_here:
        return []

    results = []
    current_date = None
    last_hall = None

    for index, (_, kind, value) in enumerate(events):
        if kind == "date":
            current_date, last_hall = value, None
        elif kind == "hall":
            last_hall = value
        elif current_date:
            hall = last_hall or next_hall_after(events, index)
            if hall == target["hall"]:
                results.append((current_date, value))

    return results


def extract_showtimes(html, target, from_fallback=False):
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    blocks = soup.find_all(["div", "li", "article", "section", "tr", "ul", "table"])
    blocks.sort(key=lambda tag: len(tag.get_text(" ", strip=True)))

    keyword = target["keyword"].lower()
    found = {}

    for block in blocks:
        text = block.get_text(" ", strip=True)
        if not text or len(text) > MAX_BLOCK_CHARS:
            continue

        if from_fallback and keyword not in text.lower():
            continue

