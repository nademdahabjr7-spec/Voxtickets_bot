#!/usr/bin/env python3
"""
Vox Cinemas showtime monitor - City Centre Almaza.

Usage:
  python check_v2.py                   run one check and exit
  python check_v2.py --interval 300    keep running, check every 300 seconds
  python check_v2.py --dry-run         print what is found; send nothing, save nothing
  python check_v2.py --test-telegram   send one test message and exit
  python check_v2.py --debug           also save fetched pages into ./debug

Environment variables:
  TELEGRAM_TOKEN   required (not needed for --dry-run)
  CHAT_ID          required (not needed for --dry-run)
  STATE_FILE       optional, default: showtimes_state.json
  LOG_FILE         optional, default: showtimes.log
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
MAX_BLOCK_CHARS = 2500  # blocks bigger than this cover too much of the page to trust

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

# Hall/format labels. They mark where one group of showtimes ends and the next begins.
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
    """Return the page text, retrying a few times. Raise FetchError if it never works."""
    last_error = "unknown error"

    for attempt in range(RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200 and len(response.text) > 500:
                return response.text
            last_error = f"HTTP {response.status_code}, {len(response.text)} chars"
        except requests.RequestException as error:
            last_error = str(error)

        if attempt < RETRIES:
            time.sleep(3 * (attempt + 1))

    raise FetchError(last_error)


def send_telegram(session, message):
    """Send a plain-text message. Retries on rate limits. Returns True when Telegram accepts it."""
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
# STATE (which showtimes were already announced)
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
        # Old format was {movie: {showtime_id: item}}. Flatten it.
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
    """Hall label that comes after a time, before the next date. Used when labels follow their times."""
    for _, kind, value in events[index + 1:]:
        if kind == "date":
            break
        if kind == "hall":
            return value
    return None


def parse_block(text, target):
    """Return (date, time) pairs in this block of text that belong to the target hall."""
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

        # Search results can mention other movies, so the title must be in the block.
        if from_fallback and keyword not in text.lower():
            continue

        times = parse_block(text, target)
        if not times:
            continue

        if from_fallback:
            link = target["url"]
        else:
            link = find_booking_link(block, target["url"])
            if link == target["url"] and not BOOKING_PATTERN.search(text):
                continue

        for date_value, time_value in times:
            raw = f"{CINEMA_NAME}|{target['movie']}|{target['hall']}|{date_value}|{time_value}"
            showtime_id = hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()

            # Smaller blocks come first, so setdefault keeps the most specific booking link.
            found.setdefault(showtime_id, {
                "movie": target["movie"],
                "hall": target["hall"],
                "cinema": CINEMA_NAME,
                "date": date_value,
                "time": time_value,
                "link": link,
                "source": "search fallback" if from_fallback else "Vox page",
            })

    return found


# =====================================
# CHECKING
# =====================================

def save_debug(name, html):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(DEBUG_DIR, f"{name}_{stamp}.html")
    with open(path, "w", encoding="utf-8") as file:
        file.write(html)
    log.info("Saved debug HTML to %s", path)


def check_target(session, target, debug=False):
    """Return {showtime_id: item}, an empty dict if nothing is listed yet, or None if both sources failed."""
    log.info("Checking %s (%s)...", target["movie"], target["hall"])
    safe_name = re.sub(r"\W+", "_", target["movie"]).strip("_")

    # 1. The Vox page itself.
    try:
        html = fetch(session, target["url"])
        if debug:
            save_debug(f"{safe_name}_vox", html)

        showtimes = extract_showtimes(html, target)
        if showtimes:
            log.info("Vox page: %d showtime(s).", len(showtimes))
            return showtimes

        # The page loaded but showed no times. It may be JavaScript-rendered, or nothing is posted yet.
        log.info("Vox page loaded but no showtimes matched. Trying search fallback.")
    except FetchError as error:
        log.warning("Vox page failed (%s). Trying search fallback.", error)

    # 2. Search fallback.
    try:
        html = fetch(session, DDG_URL, params={"q": target["fallback_query"]})
        if debug:
            save_debug(f"{safe_name}_search", html)

        showtimes = extract_showtimes(html, target, from_fallback=True)
        log.info("Search fallback: %d showtime(s).", len(showtimes))
        return showtimes
    except FetchError as error:
        log.error("Search fallback also failed (%s).", error)
        return None


def build_message(movie, hall, items):
    title = "NEW VOX SHOWTIMES DETECTED" if len(items) > 1 else "NEW VOX SHOWTIME DETECTED"

    lines = [title, "", f"Movie: {movie}", f"Hall: {hall}", f"Cinema: {CINEMA_NAME}", ""]
    lines += [f"- {item['date']} at {item['time']}" for item in items]

    links = sorted({item["link"] for item in items})
    lines += ["", "Booking:"] + links

    if any(item["source"] != "Vox page" for item in items):
        lines += ["", "Note: found through a search fallback. Confirm on the Vox site before booking."]

    return "\n".join(lines)


def run_once(session, state, dry_run=False, debug=False):
    for target in TARGETS:
        try:
            showtimes = check_target(session, target, debug)
        except Exception:
            log.exception("Error while checking %s", target["movie"])
            continue

        if showtimes is None:
            continue

        if dry_run:
            log.info("[dry run] %s: %d showtime(s)", target["movie"], len(showtimes))
            for item in showtimes.values():
                log.info("[dry run]   %s at %s (%s)", item["date"], item["time"], item["source"])
            continue

        notified = state["notified"]
        new_items = {sid: item for sid, item in showtimes.items() if sid not in notified}
        log.info("%s: %d showtime(s) found, %d new.", target["movie"], len(showtimes), len(new_items))

        if new_items:
            message = build_message(target["movie"], target["hall"], list(new_items.values()))

            if send_telegram(session, message):
                now = datetime.now().isoformat(timespec="minutes")
                for sid, item in new_items.items():
                    item["first_seen"] = now
                    notified[sid] = item
                save_state(state)
            else:
                log.error("Telegram send failed for %s. Will retry next run.", target["movie"])

        time.sleep(3)


# =====================================
# MAIN
# =====================================

def main():
    parser = argparse.ArgumentParser(description="Vox City Centre Almaza showtime monitor.")
    parser.add_argument("--interval", type=int, default=0, metavar="SECONDS",
                        help="keep running and check every N seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what is found; send nothing and save nothing")
    parser.add_argument("--test-telegram", action="store_true",
                        help="send one test message and exit")
    parser.add_argument("--debug", action="store_true",
                        help="save fetched pages into ./debug")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if not args.dry_run and not (TELEGRAM_TOKEN and CHAT_ID):
        log.error("Missing TELEGRAM_TOKEN or CHAT_ID environment variables.")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    if args.test_telegram:
        ok = send_telegram(
            session,
            f"Test from the Vox monitor at {datetime.now():%Y-%m-%d %H:%M}. Telegram is connected.",
        )
        log.info("Test message %s.", "sent" if ok else "FAILED")
        sys.exit(0 if ok else 1)

    state = load_state()

    if args.interval <= 0:
        run_once(session, state, args.dry_run, args.debug)
        return

    log.info("Checking every %d seconds. Press Ctrl+C to stop.", args.interval)
    try:
        while True:
            try:
                run_once(session, state, args.dry_run, args.debug)
            except Exception:
                log.exception("Unexpected error in this cycle. Retrying next cycle.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
    
