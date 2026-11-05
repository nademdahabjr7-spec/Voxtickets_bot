#!/usr/bin/env python3
# VOX Cinemas Monitor -> Telegram
# Monitors Dune: Part Three and Avengers: Doomsday (Infinity Vision)
# Detects new showtimes and newly bookable showtimes.

import os
import re
import json
import time
import hashlib
import html
import requests

from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =====================================
# SETTINGS
# =====================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

STATE_FILE = "showtimes_state.json"
DEBUG_DIR = "debug"

EGYPT_TZ = ZoneInfo("Africa/Cairo")

BASE_URL = "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza"

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "match": "dune part three",
        "hall": "IMAX",
        "url": BASE_URL + "&m=dune-part-three",
    },
    {
        "movie": "Avengers: Doomsday (Infinity Vision)",
        "match": "avengers doomsday",
        "hall": "MAX",
        "url": BASE_URL + "&m=avengers-doomsday-infinity-vision",
    },
]

TIME_PATTERN = re.compile(
    r"\b(?:1[0-2]|0?[1-9]):[0-5]\d\s*(?:am|pm)\b",
    re.I
)


# =====================================
# HELPERS
# =====================================

def normalize(value):
    value = (value or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def now():
    return datetime.now(EGYPT_TZ)


def make_date_url(url, date):
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query["d"] = [date.strftime("%Y%m%d")]

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query, doseq=True),
        parts.fragment
    ))


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        print("WARNING: State file could not be read.")
        return {}


def save_state(state):
    temp = STATE_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    os.replace(temp, STATE_FILE)


# =====================================
# TELEGRAM
# =====================================

def send_telegram(message, button_url=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Missing Telegram credentials.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

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
                    "url": button_url
                }
            ]]
        }

    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()

        if response.json().get("ok"):
            print("Telegram message sent.")
            return True

        print("Telegram rejected the message.")
        return False

    except Exception as error:
        print(f"Telegram error: {error}")
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

    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(20) # تم تقليل المهلة لمنع التعليق الطويل

    return driver


def save_debug(driver, name):
    os.makedirs(DEBUG_DIR, exist_ok=True)

    try:
        driver.save_screenshot(
            f"{DEBUG_DIR}/{name}.png"
        )

        with open(
            f"{DEBUG_DIR}/{name}.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(driver.page_source)

        print(f"Debug snapshot saved: {name}")

    except Exception as error:
        print(f"Debug snapshot error: {error}")


# =====================================
# LOAD VOX PAGE
# =====================================

def load_vox_page(driver, url):
    # تم تقليل عدد المحاولات إلى محاولة واحدة أو محاولتين لتسريع العملية وعدم الانتظار طويلاً
    for attempt in range(1, 3):
        try:
            print(f"Loading page (attempt {attempt}): {url}")

            try:
                driver.get(url)
            except Exception:
                pass

            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "article.movie-compare")
                )
            )

            time.sleep(1)
            return True

        except Exception as error:
            print(f"Page load failed: {type(error).__name__}")
            time.sleep(2)

    return False


# =====================================
# DISCOVER AVAILABLE DATES
# =====================================

def discover_dates(driver):
    dates = set()

    today = now().date()
    dates.add(today)

    links = driver.find_elements(
        By.CSS_SELECTOR,
        "nav.date-filter li a[href]"
    )

    for link in links:
        href = link.get_attribute("href") or ""

        match = re.search(r"[?&]d=(\d{8})", href)

        if not match:
            continue

        try:
            date = datetime.strptime(
                match.group(1),
                "%Y%m%d"
            ).date()

            if date >= today:
                dates.add(date)

        except ValueError:
            continue

    return sorted(dates)


# =====================================
# MOVIE MATCHING
# =====================================

def movie_matches(title, target):
    normalized_title = normalize(title)

    if target["match"] not in normalized_title:
        return False

    if target["movie"].startswith("Avengers"):
        return "infinity vision" in normalized_title

    return True


def hall_matches(name, target):
    normalized = normalize(name)

    if target["hall"] == "IMAX":
        return "imax" in normalized

    return "max" in normalized or "infinity vision" in normalized


# =====================================
# EXTRACT SHOWTIMES
# =====================================

def extract_target_showtimes(driver, target, target_date):
    results = {}

    articles = driver.find_elements(
        By.CSS_SELECTOR,
        "article.movie-compare"
    )

    for article in articles:
        try:
            title_elements = article.find_elements(
                By.TAG_NAME,
                "h2"
            )

            if not title_elements:
                continue

            title = title_elements[0].text.strip()

            if not movie_matches(title, target):
                continue

            hall_groups = article.find_elements(
                By.CSS_SELECTOR,
                "div.dates ol.showtimes > li"
            )

            for hall_group in hall_groups:
                strong = hall_group.find_elements(
                    By.TAG_NAME,
                    "strong"
                )

                hall = (
                    strong[0].text.strip()
                    if strong else "Standard"
                )

                if not hall_matches(hall, target):
                    continue

                items = hall_group.find_elements(
                    By.CSS_SELECTOR,
                    "ol > li"
                )

                for item in items:
                    links = item.find_elements(
                        By.CSS_SELECTOR,
                        "a.showtime"
                    )

                    link = links[0] if links else None

                    text = (
                        link.text.strip()
                        if link else item.text.strip()
                    )

                    time_match = TIME_PATTERN.search(text)

                    if not time_match:
                        continue

                    showtime = time_match.group(0).strip()

                    href = (
                        link.get_attribute("href")
                        if link else None
                    )

                    booking_open = bool(
                        href
                        and href.startswith("http")
                    )

                    booking_id = (
                        item.get_attribute("data-id") or ""
                    )

                    identity = "|".join([
                        target["movie"],
                        target["hall"],
                        target_date.isoformat(),
                        booking_id or showtime.lower()
                    ])

                    item_id = hashlib.sha256(
                        identity.encode("utf-8")
                    ).hexdigest()

                    results[item_id] = {
                        "movie": target["movie"],
                        "hall": target["hall"],
                        "date": target_date.isoformat(),
                        "time": showtime,
                        "booking_open": booking_open,
                        "link": href or target["url"],
                    }

        except Exception as error:
            print(f"Movie extraction error: {error}")

    return results


# =====================================
# NOTIFICATIONS
# =====================================

def send_new_showtime(item):
    message = (
        "🆕 <b>NEW VOX SHOWTIME!</b>\n\n"
        f"🎬 {html.escape(item['movie'])}\n"
        f"🎦 Hall: {html.escape(item['hall'])}\n"
        f"📅 Date: {item['date']}\n"
        f"🕒 Time: {html.escape(item['time'])}\n\n"
        "A new showtime has appeared on VOX."
    )

    return send_telegram(message, item["link"])


def send_booking_open(item):
    message = (
        "🚨 <b>VOX BOOKING AVAILABLE!</b>\n\n"
        f"🎬 {html.escape(item['movie'])}\n"
        f"🎦 Hall: {html.escape(item['hall'])}\n"
        f"📅 Date: {item['date']}\n"
        f"🕒 Time: {html.escape(item['time'])}\n\n"
        "🎟 VOX is displaying a selectable booking link!"
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

                print("New showtime alert sent.")

            time.sleep(1)

        if item["booking_open"] and not previous.get("booking_alerted"):
            if send_booking_open(item):
                previous["booking_alerted"] = True
                state[item_id] = previous
                save_state(state)

                print("Booking alert sent.")

            time.sleep(1)


# =====================================
# MAIN MONITOR
# =====================================

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram secrets are missing.")

    state = load_state()

    print("=" * 45)
    print("VOX CINEMAS MONITOR STARTED")
    print("Egypt time:", now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 45)

    for target in TARGETS:
        print(
            f"\nMonitoring: {target['movie']} "
            f"| {target['hall']}"
        )

        driver = new_browser()

        try:
            if not load_vox_page(driver, target["url"]):
                save_debug(driver, "vox_initial")
                print("Could not load VOX page.")
                continue

            dates = discover_dates(driver)

            print(
                "Available dates:",
                [d.isoformat() for d in dates]
            )

            for target_date in dates:
                url = make_date_url(
                    target["url"],
                    target_date
                )

                # التعديل هنا: إذا حدث Timeout أو لم تحمل الصفحة في اليوم المستقبلي، نتخطاه فوراً بدلاً من تضييع الوقت
                if target_date != now().date():
                    try:
                        driver.get(url)
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "article.movie-compare")
                            )
                        )
                    except Exception:
                        print(f"Skipping date {target_date} due to timeout/not found.")
                        continue

                results = extract_target_showtimes(
                    driver,
                    target,
                    target_date
                )

                print(
                    f"{target_date}: "
                    f"{len(results)} showtime(s) found."
                )

                process_results(results, state)

                time.sleep(1)

        except Exception as error:
            print(
                f"Monitoring error for {target['movie']}: {error}"
            )
            save_debug(driver, "vox_error")

        finally:
            driver.quit()

    save_state(state)

    print("\nVOX monitoring completed.")


if __name__ == "__main__":
    main()
                
