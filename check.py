
#!/usr/bin/env python3
# VOX Cinemas Booking Alert -> Telegram
# Dune: Part Three
# Avengers: Doomsday
# City Centre Almaza

import os
import re
import json
import time
import hashlib
import html
import logging

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

# =============== CONFIG ===============

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = (
    "https://egy.voxcinemas.com/"
    "showtimes?c=city-centre-almaza"
)

STATE_FILE = "showtimes_state.json"

TARGETS = {
    "dune": {
        "name": "Dune: Part Three",
        "match": ["dune part three"],
    },
    "avengers": {
        "name": "Avengers: Doomsday",
        "match": ["avengers doomsday"],
    },
}

TIME_PATTERN = re.compile(
    r"(?<!\d)(?:(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:am|pm)|"
    r"(?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)",
    re.I
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("VOX-ALERT")


# =============== HELPERS ===============

def normalize(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        (value or "").lower()
    ).strip()


def normalize_time(value):
    value = value.strip().lower().replace(" ", "")

    try:
        if value.endswith(("am", "pm")):
            return __import__("datetime").datetime.strptime(
                value, "%I:%M%p"
            ).strftime("%I:%M %p").lstrip("0")

        return __import__("datetime").datetime.strptime(
            value, "%H:%M"
        ).strftime("%H:%M")

    except ValueError:
        return value


def make_id(movie, hall, showtime, link):
    identity = "|".join([
        normalize(movie),
        normalize(hall),
        showtime.lower(),
        link
    ])

    return hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()


# =============== STATE ===============

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"movies": {}}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and isinstance(
            data.get("movies"), dict
        ):
            return data

    except Exception as e:
        log.error("State loading failed: %s", e)

    return {"movies": {}}


def save_state(state):
    temp = STATE_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, STATE_FILE)


# =============== TELEGRAM ===============

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
                log.info("Telegram notification sent")
                return True

            log.error("Telegram error: %s", data)

        except Exception as e:
            log.error("Telegram error: %s", e)

        time.sleep(3)

    return False


# =============== BROWSER ===============

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

            body = normalize(
                driver.find_element(
                    By.TAG_NAME, "body"
                ).text
            )

            if (
                "access denied" in body
                or "403 forbidden" in body
            ):
                raise RuntimeError("VOX Access Denied")

            return True

        except Exception as e:
            log.error("Page loading failed: %s", e)
            time.sleep(5)

    return False


# =============== BOOKING CHECK ===============

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

        blocked = [
            "disabled",
            "unavailable",
            "sold out",
            "soldout",
            "not available"
        ]

        if any(x in classes for x in blocked):
            return False

        text = normalize(link.text)

        if any(x in text for x in [
            "sold out",
            "unavailable",
            "not available"
        ]):
            return False

        parsed = urlparse(href)

        return parsed.scheme in ("http", "https")

    except StaleElementReferenceException:
        return False


# =============== MOVIE EXTRACTION ===============

def extract_showtimes(driver):

    results = {
        key: {
            "found": False,
            "showtimes": {}
        }
        for key in TARGETS
    }

    articles = driver.find_elements(
        By.CSS_SELECTOR,
        "article.movie-compare"
    )

    log.info(
        "Movie containers found: %s",
        len(articles)
    )

    for article in articles:
        try:
            titles = article.find_elements(
                By.CSS_SELECTOR, "h2"
            )

            if not titles:
                continue

            movie_title = titles[0].text.strip()
            normalized_title = normalize(movie_title)

            matched_key = None

            for key, target in TARGETS.items():
                if any(
                    phrase in normalized_title
                    for phrase in target["match"]
                ):
                    matched_key = key
                    break

            if not matched_key:
                continue

            results[matched_key]["found"] = True

            log.info(
                "Target movie found: %s",
                movie_title
            )

            groups = article.find_elements(
                By.CSS_SELECTOR,
                "div.dates ol.showtimes > li"
            )

            for group in groups:
                try:
                    strong = group.find_elements(
                        By.TAG_NAME, "strong"
                    )

                    hall = (
                        strong[0].text.strip()
                        if strong
                        else "Unknown Hall"
                    )

                    items = group.find_elements(
                        By.CSS_SELECTOR, "ol > li"
                    )

                    for item in items:
                        try:
                            links = item.find_elements(
                                By.CSS_SELECTOR,
                                "a.showtime"
                            )

                            if not links:
                                continue

                            link = links[0]

                            if not booking_is_open(link):
                                continue

                            show_text = link.text.strip()

                            match = TIME_PATTERN.search(
                                show_text
                            )

                            if not match:
                                continue

                            showtime = normalize_time(
                                match.group(0)
                            )

                            href = link.get_attribute(
                                "href"
                            )

                            booking_url = urljoin(
                                BASE_URL, href
                            )

                            movie_name = TARGETS[
                                matched_key
                            ]["name"]

                            item_id = make_id(
                                movie_name,
                                hall,
                                showtime,
                                booking_url
                            )

                            results[matched_key][
                                "showtimes"
                            ][item_id] = {
                                "movie": movie_name,
                                "hall": hall,
                                "time": showtime,
                                "link": booking_url
                            }

                        except StaleElementReferenceException:
                            continue

                except StaleElementReferenceException:
                    continue

        except StaleElementReferenceException:
            continue

    for key in TARGETS:
        log.info(
            "%s: %s open showtime(s)",
            TARGETS[key]["name"],
            len(results[key]["showtimes"])
        )

    return results


# =============== PROCESS NEW BOOKINGS ===============

def process_results(results, state):

    new_bookings = []

    for key, data in results.items():

        # Preserve state if the movie was not found.
        if not data["found"]:
            log.info(
                "%s not found on page",
                TARGETS[key]["name"]
            )
            continue

        previous = set(
            state["movies"].get(key, [])
        )

        current = set(data["showtimes"].keys())

        newly_opened = current - previous

        for item_id in newly_opened:
            item = data["showtimes"][item_id]

            new_bookings.append(item)

        # Update only after successful notification
        # when new bookings are found.
        if not newly_opened:
            state["movies"][key] = sorted(current)

    if not new_bookings:
        log.info("No new bookings detected")
        save_state(state)
        return

    lines = [
        "🎟 <b>NEW VOX BOOKINGS OPENED!</b>",
        "",
    ]

    for item in new_bookings:
        lines.extend([
            "🎬 <b>" + html.escape(item["movie"]) + "</b>",
            "🎦 Hall: " + html.escape(item["hall"]),
            "🕒 Time: " + html.escape(item["time"]),
            "",
            '<a href="' +
            html.escape(item["link"], quote=True) +
            '">🎟 OPEN BOOKING</a>',
            "",
            "━━━━━━━━━━━━━━",
            ""
        ])

    message = "\n".join(lines)

    if send_telegram(message):

        # Save new state only after Telegram succeeds.
        for key, data in results.items():
            if data["found"]:
                state["movies"][key] = sorted(
                    data["showtimes"].keys()
                )

        save_state(state)

        log.info(
            "Successfully alerted %s new booking(s)",
            len(new_bookings)
        )


# =============== MAIN ===============

def main():

    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("Missing Telegram credentials")
        return

    log.info("=" * 40)
    log.info("VOX TARGETED BOOKING MONITOR STARTED")
    log.info("=" * 40)

    state = load_state()
    driver = None

    try:
        driver = new_browser()

        if not load_vox_page(driver):
            send_telegram(
                "🔴 <b>VOX MONITOR ERROR</b>\n\n"
                "Could not load VOX showtimes page."
            )
            return

        results = extract_showtimes(driver)

        if not any(
            data["found"]
            for data in results.values()
        ):
            log.warning(
                "Neither target movie was found. "
                "State preserved."
            )
            return

        process_results(results, state)

        log.info("VOX check completed successfully")

    except Exception as e:
        log.exception("Monitor failed")

        send_telegram(
            "🔴 <b>VOX MONITOR ERROR</b>\n\n"
            + html.escape(str(e)[:1000])
        )

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        log.info("Monitor finished")


if __name__ == "__main__":
    main()
    
