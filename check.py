#!/usr/bin/env python3
# VOX Cinemas - All Movies Showtimes Monitor
# City Centre Almaza -> Telegram

import os
import re
import json
import time
import hashlib
import html
import logging

from datetime import datetime, date
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

BASE_URL = (
    "https://egy.voxcinemas.com/"
    "showtimes?c=city-centre-almaza"
)

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
    re.compile(r"\b(\d{1,2}-\d{1,2}-20\d{2})\b")
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

    for pattern in DATE_PATTERNS:
        match = pattern.search(value)

        if match:
            raw = match.group(1)

            for fmt in (
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%d-%m-%Y"
            ):
                try:
                    return datetime.strptime(
                        raw, fmt
                    ).date().isoformat()
                except ValueError:
                    pass

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

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("Telegram credentials missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
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


def load_vox_page(driver):
    for attempt in range(3):
        try:
            log.info(
                "Opening VOX page: attempt %s",
                attempt + 1
            )

            driver.get(BASE_URL)

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

def get_show_date(driver, element):
    try:
        result = driver.execute_script("""
            let el = arguments[0];

            for (let i = 0; el && i < 6; i++) {
                for (const attr of [
                    'data-date',
                    'datetime'
                ]) {
                    let value = el.getAttribute(attr);
                    if (value) return value;
                }

                el = el.parentElement;
            }

            return null;
        """, element)

        parsed = parse_date(result)

        if parsed:
            return parsed

    except Exception:
        pass

    return None


# ================= EXTRACT ALL MOVIES =================

def extract_all_showtimes(driver):
    results = {}

    articles = driver.find_elements(
        By.CSS_SELECTOR,
        "article.movie-compare"
    )

    log.info(
        "Movie containers found: %s",
        len(articles)
    )

    if not articles:
        save_debug(driver, "no_movie_containers")
        return results

    for article in articles:

        try:
            titles = article.find_elements(
                By.CSS_SELECTOR,
                "h2"
            )

            if not titles:
                continue

            movie = safe_text(titles[0])

            if not movie:
                continue

            log.info("Movie found: %s", movie)

            hall_groups = article.find_elements(
                By.CSS_SELECTOR,
                "div.dates ol.showtimes > li"
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
                        else "Unknown Hall"
                    )

                    show_date = get_show_date(
                        driver, group
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

                            booking_open = booking_is_open(
                                link
                            )

                            href = (
                                link.get_attribute("href")
                                if link
                                else None
                            )

                            booking_url = (
                                urljoin(BASE_URL, href)
                                if href
                                else BASE_URL
                            )

                            item_id = make_id(
                                movie,
                                hall,
                                show_date,
                                showtime
                            )

                            results[item_id] = {
                                "movie": movie,
                                "hall": hall,
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

    log.info(
        "Total showtimes extracted: %s",
        len(results)
    )

    return results


# ================= MESSAGE FORMAT =================

def format_showtime(item, booking_label=True):
    show_date = item["date"] or "Date unavailable"

    line = (
        f"🕒 {html.escape(show_date)}"
        f" | {html.escape(item['time'])}"
    )

    if booking_label:
        if item["booking_open"]:
            safe_url = html.escape(
                item["link"],
                quote=True
            )

            line += (
                f' | <a href="{safe_url}">'
                f'🎟 Book Now</a>'
            )
        else:
            line += " | ⏳ Booking not confirmed"

    return line


def send_initial_report(results):
    if not results:
        return False

    grouped = {}

    for item in results.values():
        key = (item["movie"], item["hall"])
        grouped.setdefault(key, []).append(item)

    messages = []

    header = (
        "🟢 <b>VOX INITIAL SHOWTIMES REPORT</b>\n"
        "📍 City Centre Almaza\n\n"
    )

    current = header

    for (movie, hall), items in grouped.items():

        block = (
            f"🎬 <b>{html.escape(movie)}</b>\n"
            f"🎦 Hall: {html.escape(hall)}\n"
        )

        items.sort(
            key=lambda x: (
                x["date"] or "9999",
                x["time"]
            )
        )

        for item in items:
            block += format_showtime(item) + "\n"

        block += "\n"

        if len(current) + len(block) > 3500:
            messages.append(current)
            current = header

        current += block

    if current.strip() != header.strip():
        messages.append(current)

    success = True

    for message in messages:
        if not send_telegram(message):
            success = False

        time.sleep(1)

    return success


# ================= PROCESS RESULTS =================

def process_results(results, state):

    for item_id, item in results.items():

        prev = state.get(item_id)

        # New showtime
        if not isinstance(prev, dict):

            msg = (
                "🆕 <b>NEW VOX SHOWTIME!</b>\n\n"
                f"🎬 {html.escape(item['movie'])}\n"
                f"🎦 Hall: {html.escape(item['hall'])}\n"
                f"📅 Date: "
                f"{html.escape(item['date'] or 'Unknown')}\n"
                f"🕒 Time: {html.escape(item['time'])}\n"
            )

            if item["booking_open"]:
                msg += (
                    "\n🎟 <b>BOOKING AVAILABLE</b>\n"
                    f'<a href="{html.escape(item["link"], quote=True)}">'
                    "Open Booking</a>"
                )
            else:
                msg += "\n⏳ Booking not confirmed yet"

            if send_telegram(msg):
                state[item_id] = {
                    "showtime_alerted": True,
                    "booking_alerted": item["booking_open"],
                    "booking_open": item["booking_open"]
                }

                save_state(state)

            time.sleep(1)
            continue

        # Booking status transition
        was_open = prev.get("booking_open", False)

        if item["booking_open"] and not was_open:

            msg = (
                "🎟 <b>VOX BOOKING AVAILABLE!</b>\n\n"
                f"🎬 {html.escape(item['movie'])}\n"
                f"🎦 Hall: {html.escape(item['hall'])}\n"
                f"📅 Date: "
                f"{html.escape(item['date'] or 'Unknown')}\n"
                f"🕒 Time: {html.escape(item['time'])}\n\n"
                f'<a href="{html.escape(item["link"], quote=True)}">'
                "🎟 OPEN BOOKING</a>"
            )

            if send_telegram(msg):
                prev["booking_alerted"] = True

            time.sleep(1)

        if not item["booking_open"]:
            prev["booking_alerted"] = False

        prev["booking_open"] = item["booking_open"]

        state[item_id] = prev

        save_state(state)


# ================= MAIN =================

def main():

    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("Missing TELEGRAM_TOKEN or CHAT_ID")
        return

    log.info("=" * 45)
    log.info("VOX ALL MOVIES MONITOR STARTED")
    log.info("Time: %s", now())
    log.info("=" * 45)

    state = load_state()
    driver = None

    try:
        driver = new_browser()

        if not load_vox_page(driver):
            send_telegram(
                "🔴 <b>VOX MONITOR ERROR</b>\n"
                "Could not load the VOX showtimes page."
            )
            return

        results = extract_all_showtimes(driver)

        if not results:
            log.warning("No showtimes extracted")

            send_telegram(
                "⚠️ <b>VOX MONITOR WARNING</b>\n\n"
                "The page loaded, but no showtimes "
                "were extracted.\n"
                "Debug files were saved for inspection."
            )

            return

        log.info(
            "Successfully extracted %s showtimes",
            len(results)
        )

        # First run: send complete report
        if not state:

            log.info("First run: sending initial report")

            if send_initial_report(results):

                for item_id, item in results.items():
                    state[item_id] = {
                        "showtime_alerted": True,
                        "booking_alerted": item["booking_open"],
                        "booking_open": item["booking_open"]
                    }

                save_state(state)

            else:
                log.error("Initial report was not fully sent")

        else:
            process_results(results, state)

        log.info("VOX check completed successfully")

    except Exception as e:
        log.exception("Monitor failed")

        send_telegram(
            "🔴 <b>VOX MONITOR ERROR</b>\n\n"
            f"{html.escape(str(e)[:1000])}"
        )

        if driver:
            save_debug(driver, "main_exception")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        save_state(state)

        log.info("Monitor finished")


if __name__ == "__main__":
    main()
    
