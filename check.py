#!/usr/init/env python3
# VOX Cinemas - Targeted Movies Monitor (Main Page Search)
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

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "match": ["dune part three", "dune"],
        "hall": "IMAX",
        "hall_match": ["imax"],
    },
    {
        "movie": "Avengers: Doomsday (Infinity Vision)",
        "match": ["avengers doomsday", "infinity vision"],
        "hall": "Infinity Vision",
        "hall_match": ["infinity vision", "infinity"],
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

def send_telegram(message, button_url=None):
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
            log.info("Opening VOX main page: attempt %s", attempt + 1)
            driver.get(BASE_URL)

            WebDriverWait(driver, 25).until(
                lambda d: d.execute_script(
                    "return document.readyState"
                ) in ("interactive", "complete")
            )

            time.sleep(5)

            page_text = normalize(
                driver.find_element(By.TAG_NAME, "body").text
            )

            if "access denied" in page_text or "403 forbidden" in page_text:
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

        if not href or href.startswith(("javascript:", "#")):
            return False

        if link.get_attribute("disabled") is not None:
            return False

        if (link.get_attribute("aria-disabled") or "").lower() == "true":
            return False

        classes = normalize(link.get_attribute("class") or "")
        blocked_classes = ["disabled", "unavailable", "sold out", "soldout", "not available"]

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
            for (let i = 0; el && i < 8; i++) {
                for (const attr of ['data-date', 'datetime', 'data-day', 'id']) {
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

        container_text = driver.execute_script("""
            let el = arguments[0];
            for (let i = 0; el && i < 4; i++) {
                el = el.parentElement;
            }
            return el ? el.innerText : '';
        """, element)

        parsed = parse_date(container_text)
        if parsed:
            return parsed

    except Exception:
        pass

    return now().date().isoformat()


# ================= EXTRACT AND FILTER =================

def extract_and_filter_showtimes(driver):
    results = {}

    articles = driver.find_elements(By.CSS_SELECTOR, "article.movie-compare")
    log.info("Total movie containers found on page: %s", len(articles))

    if not articles:
        save_debug(driver, "no_movie_containers")
        return results

    for article in articles:
        try:
            titles = article.find_elements(By.CSS_SELECTOR, "h2")
            if not titles:
                continue

            movie_title = safe_text(titles[0])
            norm_movie = normalize(movie_title)

            # مطابقة الفيلم مع الأهداف المطلوبة
            matched_target = None
            for target in TARGETS:
                if any(m in norm_movie for m in target["match"]):
                    matched_target = target
                    break

            if not matched_target:
                continue

            log.info("Matched target movie on page: %s", movie_title)

            hall_groups = article.find_elements(By.CSS_SELECTOR, "div.dates ol.showtimes > li")

            for group in hall_groups:
                try:
                    strong = group.find_elements(By.TAG_NAME, "strong")
                    hall_text = safe_text(strong[0]) if strong else safe_text(group)
                    norm_hall = normalize(hall_text)

                    # مطابقة قاعة العرض (IMAX / Infinity Vision)
                    if not any(h in norm_hall for h in matched_target["hall_match"]):
                        continue

                    show_date = get_show_date(driver, group)
                    items = group.find_elements(By.CSS_SELECTOR, "ol > li")

                    for item in items:
                        try:
                            links = item.find_elements(By.CSS_SELECTOR, "a.showtime")
                            link = links[0] if links else None

                            text = safe_text(link) if link else safe_text(item)
                            match = TIME_PATTERN.search(text)

                            if not match:
                                continue

                            showtime = normalize_time(match.group(0))
                            booking_open = booking_is_open(link)

                            href = link.get_attribute("href") if link else None
                            booking_url = urljoin(BASE_URL, href) if href else BASE_URL

                            item_id = make_id(
                                matched_target["movie"],
                                matched_target["hall"],
                                show_date,
                                showtime
                            )

                            results[item_id] = {
                                "movie": matched_target["movie"],
                                "hall": matched_target["hall"],
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

    log.info("Extracted %s showtime(s) for target movies.", len(results))
    return results


# ================= PROCESS RESULTS =================

def process_results(results, state):
    for item_id, item in results.items():
        prev = state.get(item_id)

        if not isinstance(prev, dict):
            msg = (
                "🆕 <b>NEW VOX SHOWTIME!</b>\n\n"
                f"🎬 {html.escape(item['movie'])}\n"
                f"🎦 Hall: {html.escape(item['hall'])}\n"
                f"📅 Date: {html.escape(item['date'] or 'Unknown')}\n"
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

            if send_telegram(msg, item["link"] if item["booking_open"] else None):
                state[item_id] = {
                    "showtime_alerted": True,
                    "booking_alerted": item["booking_open"],
                    "booking_open": item["booking_open"]
                }
                save_state(state)

            time.sleep(1)
            continue

        was_open = prev.get("booking_open", False)

        if item["booking_open"] and not was_open:
            msg = (
                "🎟 <b>VOX BOOKING AVAILABLE!</b>\n\n"
                f"🎬 {html.escape(item['movie'])}\n"
                f"🎦 Hall: {html.escape(item['hall'])}\n"
                f"📅 Date: {html.escape(item['date'] or 'Unknown')}\n"
                f"🕒 Time: {html.escape(item['time'])}\n\n"
                f'<a href="{html.escape(item["link"], quote=True)}">'
                "🎟 OPEN BOOKING</a>"
            )

            if send_telegram(msg, item["link"]):
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
    log.info("VOX TARGETED MONITOR STARTED")
    log.info("Time: %s", now())
    log.info("=" * 45)

    state = load_state()
    driver = None

    try:
        driver = new_browser()

        if not load_vox_page(driver):
            send_telegram(
                "🔴 <b>VOX MONITOR ERROR</b>\n"
                "Could not load the VOX main showtimes page."
            )
            return

        results = extract_and_filter_showtimes(driver)
        process_results(results, state)

        send_telegram(
            "🟢 <b>VOX Monitor Status</b>\n\n"
            f"📅 Time: {now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔍 Checked page successfully. Found {len(results)} target showtime(s)."
        )

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
                
