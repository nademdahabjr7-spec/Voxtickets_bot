#!/usr/bin/env python3
# VOX Cinemas Showtimes Monitor -> Telegram
# Dune: Part Three (IMAX)
# Avengers: Doomsday (Infinity Vision)
# City Centre Almaza

import os
import re
import json
import time
import hashlib
import html
import logging

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException
)

# ================= CONFIG =================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Set SEND_STATUS=true if you want a status message
# after every successful run.
SEND_STATUS = os.getenv("SEND_STATUS", "false").lower() == "true"

BASE_URL = (
    "https://egy.voxcinemas.com/"
    "showtimes?c=city-centre-almaza"
)

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "match": ["dune part three"],
        "hall": "IMAX",
        "hall_match": ["imax"],
        "url": BASE_URL + "&m=dune-part-three",
    },
    {
        "movie": "Avengers: Doomsday (Infinity Vision)",
        "match": [
            "avengers doomsday",
            "avengers doomsday infinity vision",
        ],
        "hall": "Infinity Vision",
        "hall_match": ["infinity vision"],
        "url": BASE_URL + "&m=avengers-doomsday-infinity-vision",
    },
]

STATE_FILE = "showtimes_state.json"
DEBUG_DIR = "debug"

EGYPT_TZ = ZoneInfo("Africa/Cairo")

TIME_PATTERN = re.compile(
    r"(?<!\d)(?:(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:am|pm)|"
    r"(?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)",
    re.I
)

DATE_PATTERNS = [
    re.compile(r"\b(20\d{2}-\d{1,2}-\d{1,2})\b"),
    re.compile(r"\b(\d{1,2}/\d{1,2}/20\d{2})\b"),
    re.compile(r"\b(\d{1,2}-\d{1,2}-20\d{2})\b"),
    re.compile(
        r"\b(\d{1,2}\s+"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)"
        r"\s*,?\s*20\d{2})\b",
        re.I
    ),
    re.compile(
        r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{1,2}\s*,?\s*20\d{2})\b",
        re.I
    ),
    re.compile(
        r"\b(\d{1,2}\s+"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?))\b",
        re.I
    ),
    re.compile(
        r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{1,2})\b",
        re.I
    )
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("VOX-MONITOR")


# ================= HELPERS =================

def now():
    return datetime.now(EGYPT_TZ)


def normalize(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        (value or "").lower().replace("&", " and ")
    ).strip()


def safe_text(element):
    try:
        return element.text.strip()
    except StaleElementReferenceException:
        return ""


def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    # Relative date labels
    lowered = value.lower()

    if re.search(r"\btoday\b", lowered):
        return now().date().isoformat()

    if re.search(r"\btomorrow\b", lowered):
        return (now().date() + timedelta(days=1)).isoformat()

    for index, pattern in enumerate(DATE_PATTERNS):
        match = pattern.search(value)

        if not match:
            continue

        raw = match.group(1).strip()

        formats = []

        if index == 0:
            formats = ["%Y-%m-%d"]

        elif index == 1:
            # Egyptian date convention: DD/MM/YYYY
            formats = ["%d/%m/%Y"]

        elif index == 2:
            formats = ["%d-%m-%Y"]

        elif index == 3:
            formats = ["%d %B %Y", "%d %b %Y"]

        elif index == 4:
            formats = ["%B %d %Y", "%b %d %Y"]

        elif index == 5:
            formats = ["%d %B", "%d %b"]

        elif index == 6:
            formats = ["%B %d", "%b %d"]

        for fmt in formats:
            try:
                parsed = datetime.strptime(raw, fmt)

                if "%Y" in fmt:
                    return parsed.date().isoformat()

                # A date without a year is interpreted using
                # the current year, with year rollover for
                # dates sufficiently far in the past.
                today = now().date()
                candidate = parsed.date().replace(year=today.year)

                if candidate < today - timedelta(days=30):
                    candidate = candidate.replace(year=today.year + 1)

                return candidate.isoformat()

            except ValueError:
                continue

    return None


def normalize_time(value):
    value = value.strip().lower().replace(" ", "")

    if re.search(r"(am|pm)$", value):
        try:
            return datetime.strptime(
                value, "%I:%M%p"
            ).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            return value

    try:
        return datetime.strptime(
            value, "%H:%M"
        ).strftime("%H:%M")
    except ValueError:
        return value


def make_id(movie, hall, show_date, showtime):
    identity = "|".join([
        normalize(movie),
        normalize(hall),
        show_date or "unknown",
        showtime.lower()
    ])

    return hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()


# ================= STATE =================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception as e:
        log.error("State loading failed: %s", e)
        return {}


def save_state(state):
    temp = STATE_FILE + ".tmp"

    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp, STATE_FILE)

    except Exception as e:
        log.error("State saving failed: %s", e)


# ================= TELEGRAM =================

def send_telegram(message, button_url=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("Telegram credentials missing")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    if button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {
                    "text": "🎟 Open VOX Booking",
                    "url": button_url,
                }
            ]]
        }

    for attempt in range(3):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=20
            )

            data = response.json()

            if data.get("ok"):
                log.info("Telegram message sent")
                return True

            log.error("Telegram error: %s", data)

        except Exception as e:
            log.error(
                "Telegram attempt %s failed: %s",
                attempt + 1,
                e
            )

        time.sleep(2)

    return False


# ================= DEBUG =================

def save_debug(driver, reason):
    os.makedirs(DEBUG_DIR, exist_ok=True)

    stamp = now().strftime("%Y%m%d_%H%M%S")

    try:
        with open(
            f"{DEBUG_DIR}/{stamp}.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(driver.page_source)

        driver.save_screenshot(
            f"{DEBUG_DIR}/{stamp}.png"
        )

        log.info("Debug files saved: %s", reason)

    except Exception as e:
        log.error("Debug saving failed: %s", e)


def save_date_debug(movie, hall, candidates):
    os.makedirs(DEBUG_DIR, exist_ok=True)

    path = os.path.join(DEBUG_DIR, "date_candidates.log")

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(
                f"\n[{now().isoformat()}] "
                f"Movie: {movie} | Hall: {hall}\n"
            )

            for candidate in candidates:
                f.write(f"  - {candidate}\n")

    except Exception as e:
        log.error("Date debug saving failed: %s", e)


# ================= BROWSER =================

def new_browser():
    options = Options()

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    options.add_argument(
        "user-agent=Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(40)

    return driver


def load_vox_page(driver, url):
    for attempt in range(3):
        try:
            log.info(
                "Opening VOX page: attempt %s",
                attempt + 1
            )

            driver.get(url)

            WebDriverWait(driver, 25).until(
                lambda d: d.execute_script(
                    "return document.readyState"
                ) in ("interactive", "complete")
            )

            time.sleep(5)

            page_text = normalize(
                driver.find_element(
                    By.TAG_NAME, "body"
                ).text
            )

            if (
                "access denied" in page_text
                or "403 forbidden" in page_text
            ):
                raise RuntimeError("VOX Access Denied")

            return True

        except Exception as e:
            log.error("Page loading failed: %s", e)
            time.sleep(5)

    save_debug(driver, "page_loading_failed")
    return False


# ================= BOOKING STATUS =================

def booking_is_open(link):
    if not link:
        return False

    try:
        href = link.get_attribute("href") or ""

        if not href:
            return False

        if href.startswith(("javascript:", "#")):
            return False

        if link.get_attribute("disabled") is not None:
            return False

        if (
            link.get_attribute("aria-disabled") or ""
        ).lower() == "true":
            return False

        classes = normalize(
            link.get_attribute("class") or ""
        )

        blocked_classes = [
            "disabled",
            "unavailable",
            "sold out",
            "soldout",
            "not available"
        ]

        if any(x in classes for x in blocked_classes):
            return False

        parsed = urlparse(href)

        return parsed.scheme in ("http", "https")

    except StaleElementReferenceException:
        return False


# ================= DATE EXTRACTION =================

def get_show_date(driver, element, movie="", hall=""):
    """
    Search for the date around the showtime group.

    Never invent today's date when extraction fails.
    Returns None if no reliable date is found.
    """

    candidates = []

    try:
        candidates = driver.execute_script("""
            const start = arguments[0];
            const found = [];
            const seen = new Set();

            function add(value) {
                if (!value) return;

                value = String(value).trim();

                if (!value || seen.has(value)) return;

                seen.add(value);
                found.push(value);
            }

            function isDateElement(el) {
                if (!el || !el.getAttribute) return false;

                const marker = (
                    (el.className || '') + ' ' +
                    (el.id || '')
                ).toLowerCase();

                return /date|day|calendar/.test(marker);
            }

            let el = start;

            for (let level = 0; el && level < 8; level++) {

                // Explicit date attributes
                for (const attr of [
                    'data-date',
                    'datetime',
                    'data-day'
                ]) {
                    add(el.getAttribute(attr));
                }

                // Only accept ID when it looks date-related
                const id = el.getAttribute('id') || '';

                if (/date|day|calendar/i.test(id)) {
                    add(id);
                }

                // Date-labelled element itself
                if (isDateElement(el)) {
                    add(el.innerText);
                    add(el.textContent);
                }

                // Look at nearby preceding date labels
                let sibling = el.previousElementSibling;

                for (let j = 0; sibling && j < 4; j++) {
                    if (isDateElement(sibling)) {
                        add(sibling.getAttribute('data-date'));
                        add(sibling.getAttribute('datetime'));
                        add(sibling.innerText);
                        add(sibling.textContent);
                    }

                    sibling = sibling.previousElementSibling;
                }

                // Direct children of the current container
                if (el.children) {
                    for (const child of el.children) {
                        if (isDateElement(child)) {
                            add(child.getAttribute('data-date'));
                            add(child.getAttribute('datetime'));
                            add(child.innerText);
                            add(child.textContent);
                        }
                    }
                }

                el = el.parentElement;
            }

            return found;
        """, element)

        if not isinstance(candidates, list):
            candidates = []

        # Test the closest candidates first
        for candidate in candidates:
            parsed = parse_date(candidate)

            if parsed:
                log.info(
                    "Date found for %s | %s: %s",
                    movie,
                    hall,
                    parsed
                )
                return parsed

        save_date_debug(movie, hall, candidates)

        log.warning(
            "Date not found for %s | %s. Candidates: %s",
            movie,
            hall,
            candidates[:15]
        )

    except Exception as e:
        log.warning("Date extraction failed: %s", e)

    return None


# ================= MATCHING HELPERS =================

def movie_matches(title, target):
    title = normalize(title)
    return any(
        normalize(name) in title
        for name in target["match"]
    )


def hall_matches(name, target):
    name = normalize(name)
    return any(
        normalize(hall) in name
        for hall in target["hall_match"]
    )


# ================= EXTRACT TARGET SHOWTIMES =================

def extract_target_showtimes(driver, target):
    results = {}

    articles = driver.find_elements(
        By.CSS_SELECTOR,
        "article.movie-compare"
    )

    log.info(
        "Movie containers found for %s: %s",
        target["movie"],
        len(articles)
    )

    for article in articles:
        try:
            titles = article.find_elements(
                By.CSS_SELECTOR,
                "h2"
            )

            if not titles:
                continue

            movie = safe_text(titles[0])

            if not movie or not movie_matches(movie, target):
                continue

            log.info("Target movie matched: %s", movie)

            hall_groups = article.find_elements(
                By.CSS_SELECTOR,
                "div.dates ol.showtimes > li"
            )

            log.info(
                "Hall groups found for %s: %s",
                movie,
                len(hall_groups)
            )

            for group in hall_groups:
                try:
                    strong = group.find_elements(
                        By.TAG_NAME,
                        "strong"
                    )

                    hall = (
                        safe_text(strong[0])
                        if strong
                        else safe_text(group)
                    )

                    if not hall_matches(hall, target):
                        continue

                    show_date = get_show_date(
                        driver,
                        group,
                        movie,
                        hall
                    )

                    items = group.find_elements(
                        By.CSS_SELECTOR,
                        "ol > li"
                    )

                    for item in items:
                        try:
                            links = item.find_elements(
                                By.CSS_SELECTOR,
                                "a.showtime"
                            )

                            link = links[0] if links else None

                            text = (
                                safe_text(link)
                                if link
                                else safe_text(item)
                            )

                            match = TIME_PATTERN.search(text)

                            if not match:
                                continue

                            showtime = normalize_time(
                                match.group(0)
                            )

                            booking_open = booking_is_open(link)

                            href = (
                                link.get_attribute("href")
                                if link
                                else None
                            )

                            booking_url = (
                                urljoin(target["url"], href)
                                if href
                                else target["url"]
                            )

                            item_id = make_id(
                                target["movie"],
                                target["hall"],
                                show_date,
                                showtime
                            )

                            results[item_id] = {
                                "movie": target["movie"],
                                "hall": target["hall"],
                                "date": show_date,
                                "time": showtime,
                                "booking_open": booking_open,
                                "link": booking_url
                            }

                        except StaleElementReferenceException:
                            continue

                except StaleElementReferenceException:
                    continue

        except StaleElementReferenceException:
            continue

    return results


# ================= PROCESS RESULTS =================

def process_results(results, state):
    for item_id, item in results.items():
        prev = state.get(item_id)
        
