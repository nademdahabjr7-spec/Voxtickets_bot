#!/usr/bin/env python3
# VOX Cinemas Monitor -> Telegram
# Dune: Part Three (IMAX)
# Avengers: Doomsday (Infinity Vision)

import os
import re
import json
import time
import hashlib
import html
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)

# =====================================
# SETTINGS
# =====================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

STATE_FILE = "showtimes_state.json"
DEBUG_DIR = "debug"

EGYPT_TZ = ZoneInfo("Africa/Cairo")

BASE_URL = (
    "https://egy.voxcinemas.com/showtimes"
    "?c=city-centre-almaza"
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

TIME_PATTERN = re.compile(
    r"(?<!\d)(?:"
    r"(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:am|pm)"
    r"|(?:[01]?\d|2[0-3]):[0-5]\d"
    r")(?!\d)",
    re.I,
)

ISO_DATE_PATTERN = re.compile(
    r"\b(20\d{2}-\d{1,2}-\d{1,2})\b"
)

HUMAN_DATE_PATTERN = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?"
    r"\s*(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"(?:\s+(20\d{2}))?\b",
    re.I,
)

MONTH_DATE_PATTERN = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b",
    re.I,
)

# =====================================
# LOGGING
# =====================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("VOX-Monitor")


def now():
    return datetime.now(EGYPT_TZ)


# =====================================
# HELPERS
# =====================================

def normalize(value):
    value = (value or "").lower()
    value = value.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def safe_text(element):
    try:
        return element.text.strip()
    except StaleElementReferenceException:
        return ""


def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    match = ISO_DATE_PATTERN.search(value)

    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            pass

    match = HUMAN_DATE_PATTERN.search(value)

    if match:
        day = int(match.group(1))
        month = match.group(2).title()
        year = int(match.group(3)) if match.group(3) else now().year

        try:
            return datetime.strptime(
                f"{day} {month} {year}",
                "%d %b %Y"
            ).date().isoformat()
        except ValueError:
            pass

    match = MONTH_DATE_PATTERN.search(value)

    if match:
        month = match.group(1).title()
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else now().year

        try:
            return datetime.strptime(
                f"{day} {month} {year}",
                "%d %b %Y"
            ).date().isoformat()
        except ValueError:
            pass

    return None


def normalize_time(value):
    value = value.strip().lower()
    value = re.sub(r"\s+", "", value)

    if re.search(r"(am|pm)$", value):
        try:
            return datetime.strptime(
                value,
                "%I:%M%p"
            ).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            return value

    try:
        return datetime.strptime(
            value,
            "%H:%M"
        ).strftime("%H:%M")
    except ValueError:
        return value


# =====================================
# STATE MANAGEMENT
# =====================================

def load_state():
    if not os.path.exists(STATE_FILE):
        log.info("No previous state found. Starting fresh.")
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        if isinstance(state, dict):
            log.info("Previous state loaded.")
            return state

    except (OSError, json.JSONDecodeError) as error:
        log.error("State loading error: %s", error)

    return {}


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, STATE_FILE)
        return True

    except OSError as error:
        log.error("State saving error: %s", error)
        return False


# =====================================
# TELEGRAM
# =====================================

def send_telegram(message, button_url=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("Telegram credentials missing.")
        return False

    api_url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
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

    for attempt in range(1, 4):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=20
            )

            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                log.info("Telegram notification sent.")
                return True

            log.error("Telegram API error: %s", result)

        except requests.RequestException as error:
            log.error(
                "Telegram attempt %s failed: %s",
                attempt,
                error
            )

        time.sleep(2)

    return False


# =====================================
# CHROME
# =====================================

def new_browser():
    options = Options()

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")

    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)

    return driver


# =====================================
# DEBUG
# =====================================

def save_debug(driver, name):
    os.makedirs(DEBUG_DIR, exist_ok=True)

    try:
        driver.save_screenshot(
            os.path.join(DEBUG_DIR, name + ".png")
        )

        with open(
            os.path.join(DEBUG_DIR, name + ".html"),
            "w",
            encoding="utf-8"
        ) as file:
            file.write(driver.page_source)

        log.info("Debug files saved: %s", name)

    except Exception as error:
        log.error("Debug saving failed: %s", error)


# =====================================
# PAGE LOADING
# =====================================

def load_vox_page(driver, url):
    for attempt in range(1, 4):
        try:
            log.info(
                "Loading VOX page, attempt %s: %s",
                attempt,
                url
            )

            try:
                driver.get(url)
            except TimeoutException:
                log.warning("Page navigation timed out.")

            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script(
                    "return document.readyState"
                ) in ("interactive", "complete")
            )

            time.sleep(3)

            page_text = normalize(driver.find_element(
                By.TAG_NAME,
                "body"
            ).text)

            if (
                "access denied" in page_text
                or "request blocked" in page_text
            ):
                raise RuntimeError("VOX access blocked.")

            return True

        except Exception as error:
            log.error(
                "Page loading failed: %s",
                error
            )

            time.sleep(3)

    return False


# =====================================
# MOVIE MATCHING
# =====================================

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


# =====================================
# DATE EXTRACTION
# =====================================

def extract_group_date(driver, element):
    try:
        data = driver.execute_script("""
            let el = arguments[0];
            let result = [];

            for (let i = 0; el && i < 6; i++, el = el.parentElement) {
                result.push({
                    text: el.innerText || '',
                    date: el.getAttribute('data-date') || '',
                    datetime: el.getAttribute('datetime') || '',
                    label: el.getAttribute('aria-label') || ''
                });
            }

            return result;
        """, element)

        for item in data:
            for field in ("date", "datetime", "label"):
                parsed = parse_date(item.get(field))
                if parsed:
                    return parsed

        for item in data:
            parsed = parse_date(item.get("text"))
            if parsed:
                return parsed

    except Exception as error:
        log.warning("Date extraction warning: %s", error)

    return None


# =====================================
# BOOKING DETECTION
# =====================================

def is_booking_link_available(link):
    try:
        href = link.get_attribute("href")
        if not href:
            return False

        if not href.startswith(("http://", "https://")):
            return False

        if link.get_attribute("disabled") is not None:
            return False

        aria_disabled = (
            link.get_attribute("aria-disabled") or ""
        ).lower()

        if aria_disabled == "true":
            return False

        classes = normalize(
            link.get_attribute("class") or ""
        )

        if any(word in classes.split() for word in (
            "disabled",
            "unavailable",
            "soldout",
            "sold-out",
        )):
            return False

        return True

    except StaleElementReferenceException:
        return False


# =====================================
# SHOWTIME EXTRACTION
# =====================================

def extract_target_showtimes(driver, target):
    results = {}

    articles = driver.find_elements(
        By.CSS_SELECTOR,
        "article.movie-compare"
    )

    log.info(
        "Movie articles found: %s",
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

            title = safe_text(titles[0])

            if not movie_matches(title, target):
                continue

            log.info("Target movie found: %s", title)

            hall_groups = article.find_elements(
                By.CSS_SELECTOR,
                "div.dates ol.showtimes > li"
            )

            for hall_group in hall_groups:
                try:
                    strong = hall_group.find_elements(
                        By.TAG_NAME,
                        "strong"
                    )

                    hall = (
                        safe_text(strong[0])
                        if strong
                        else safe_text(hall_group)
                    )

                    if not hall_matches(hall, target):
                        continue

                    show_date = extract_group_date(
                        driver,
                        hall_group
                    )

                    items = hall_group.find_elements(
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

                            booking_open = (
                                is_booking_link_available(link)
                                if link
                                else False
                            )

                            href = (
                                link.get_attribute("href")
                                if link
                                else None
                            )

                            booking_id = (
                                item.get_attribute("data-id")
                                or ""
                            )

                            identity = "|".join([
                                target["movie"],
                                target["hall"],
                                show_date or "unknown-date",
                                showtime.lower(),
                                booking_id,
                            ])

                            item_id = hashlib.sha256(
                                identity.encode("utf-8")
                            ).hexdigest()

                            results[item_id] = {
                                "movie": target["movie"],
                                "hall": target["hall"],
                                "date": show_date,
                                "time": showtime,
                                "booking_open": booking_open,
                                "link": (
                                    urljoin(target["url"], href)
                                    if href
                                    else target["url"]
                                ),
                            }

                        except StaleElementReferenceException:
                            log.warning(
                                "Showtime element changed during extraction."
                            )

                except Exception as error:
                    log.warning(
                        "Hall extraction error: %s",
                        error
                    )

        except Exception as error:
            log.warning(
                "Movie extraction error: %s",
                error
            )

    return results


# =====================================
# NOTIFICATIONS
# =====================================

def date_label(value):
    return value if value else "Date not identified"


def send_new_showtime(item):
    message = (
        "🆕 <b>NEW VOX SHOWTIME!</b>\n\n"
        f"🎬 {html.escape(item['movie'])}\n"
        f"🎦 Hall: {html.escape(item['hall'])}\n"
        f"📅 Date: {html.escape(date_label(item['date']))}\n"
        f"🕒 Time: {html.escape(item['time'])}\n\n"
        "A new showtime has appeared on VOX."
    )

    return send_telegram(message, item["link"])


def send_booking_open(item):
    message = (
        "🎟 <b>VOX BOOKING LINK AVAILABLE!</b>\n\n"
        f"🎬 {html.escape(item['movie'])}\n"
        f"🎦 Hall: {html.escape(item['hall'])}\n"
        f"📅 Date: {html.escape(date_label(item['date']))}\n"
        f"🕒 Time: {html.escape(item['time'])}\n\n"
        "VOX is displaying an enabled showtime link. "
        "Please verify the booking page."
    )

    return send_telegram(message, item["link"])


# =====================================
# PROCESS RESULTS
# =====================================

def process_results(results, state):
    for item_id, item in results.items():

        previous = state.get(item_id, {})

        if not isinstance(previous, dict):
            previous = {}

        if not previous.get("showtime_alerted"):

            if send_new_showtime(item):
                previous["showtime_alerted"] = True
                state[item_id] = previous
                save_state(state)

                log.info("New showtime alert sent.")

            time.sleep(1)

        if (
            item["booking_open"]
            and not previous.get("booking_alerted")
        ):

            if send_booking_open(item):
                previous["booking_alerted"] = True
                state[item_id] = previous
                save_state(state)

                log.info("Booking alert sent.")

            time.sleep(1)


# =====================================
# MONITOR
# =====================================

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_TOKEN or CHAT_ID."
        )

    state = load_state()

    log.info("=" * 50)
    log.info("VOX CINEMAS MONITOR STARTED")
    log.info(
        "Egypt time: %s",
        now().strftime("%Y-%m-%d %H:%M:%S")
    )
    log.info("=" * 50)

    driver = None
    successful_pages = 0

    try:
        driver = new_browser()

        for target in TARGETS:

            log.info(
                "Monitoring: %s | %s",
                target["movie"],
                target["hall"]
            )

            if not load_vox_page(driver, target["url"]):
                save_debug(
                    driver,
                    normalize(target["movie"]).replace(" ", "_")
                    + "_load_error"
                )

                log.error("Could not load target page.")
                continue

            successful_pages += 1

            results = extract_target_showtimes(
                driver,
                target
            )

            log.info(
                "Showtimes found for %s: %s",
                target["movie"],
                len(results)
            )

            process_results(results, state)

    except Exception as error:
        log.error("Critical error in monitor: %s", error)

        if driver:
            save_debug(driver, "critical_error")

    finally:
        if driver:
            driver.quit()

    save_state(state)
    log.info("VOX monitoring comp
