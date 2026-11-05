
#!/usr/bin/env python3

"""
VOX Cinemas Ticket Monitor V2
Dune: Part Three - IMAX
Avengers: Doomsday - MAX

Runs once per GitHub Actions workflow.
State is persisted in showtimes_state.json.
"""

import os
import re
import json
import time
import hashlib
import requests

from bs4 import BeautifulSoup
from urllib.parse import urljoin


# =====================================
# SETTINGS
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
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

TIMEOUT = 25


# =====================================
# TARGET MOVIES
# =====================================

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "hall": "IMAX",
        "url": (
            "https://egy.voxcinemas.com/showtimes"
            "?c=city-centre-almaza&m=dune-part-three"
        ),
    },
    {
        "movie": "Avengers: Doomsday",
        "hall": "MAX",
        "url": (
            "https://egy.voxcinemas.com/showtimes"
            "?c=city-centre-almaza"
            "&m=avengers-doomsday-infinity-vision"
        ),
    },
]


# =====================================
# DETECTION PATTERNS
# =====================================

DATE_PATTERN = re.compile(
    r"\b(?:"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s*"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\s+\d{1,2}|"
    r"\d{1,2}\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r")\b",
    re.I,
)

TIME_PATTERN = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?\b"
    r"|\b(?:1[0-2]|0?[1-9])\s*(?:am|pm)\b",
    re.I,
)

BOOKING_PATTERN = re.compile(
    r"\b(book now|book tickets|select seats|choose seats|"
    r"buy tickets|book)\b",
    re.I,
)

BOOKING_URL_PATTERN = re.compile(
    r"book|booking|seat|checkout|ticket",
    re.I,
)

ACCESS_DENIED_PATTERN = re.compile(
    r"access denied|request blocked|"
    r"reference #[0-9a-f]+|errors\.edgesuite",
    re.I,
)


# =====================================
# TELEGRAM
# =====================================

def send_telegram(session, message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = session.post(
            url,
            json=payload,
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        if result.get("ok"):
            print("Telegram notification sent.")
            return True

        print("Telegram rejected the message.")
        return False

    except requests.RequestException as error:
        print(f"Telegram error: {error}")
        return False


# =====================================
# STATE MANAGEMENT
# =====================================

def load_state():

    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except (json.JSONDecodeError, OSError) as error:
        print(f"State loading error: {error}")

    return {}


def save_state(state):

    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(temp_file, STATE_FILE)


# =====================================
# HALL DETECTION
# =====================================

def hall_matches(text, hall):

    if hall == "IMAX":
        return bool(
            re.search(r"\bIMAX\b", text, re.I)
        )

    if hall == "MAX":
        return bool(
            re.search(r"\bMAX\b", text, re.I)
        )

    return False


# =====================================
# PAGE VALIDATION
# =====================================

def validate_page(response):

    if response.status_code != 200:
        print(
            f"VOX returned HTTP {response.status_code}"
        )
        return False

    html = response.text

    if len(html) < 500:
        print("Page content is too short.")
        return False

    if ACCESS_DENIED_PATTERN.search(html):
        print("VOX Access Denied detected.")
        return False

    return True


# =====================================
# BOOKING LINK DETECTION
# =====================================

def get_booking_links(tag, base_url):

    links = []

    for anchor in tag.find_all("a", href=True):

        href = urljoin(base_url, anchor["href"])

        label = anchor.get_text(" ", strip=True)

        if (
            BOOKING_PATTERN.search(label)
            or BOOKING_URL_PATTERN.search(href)
        ):
            links.append(href)

    return links


# =====================================
# EXTRACT SHOWTIMES
# =====================================

def extract_showtimes(html, target):

    soup = BeautifulSoup(html, "html.parser")

    for element in soup(
        ["script", "style", "noscript", "svg"]
    ):
        element.decompose()

    candidates = soup.find_all(
        ["div", "li", "article", "section"]
    )

    candidates.sort(
        key=lambda tag: len(
            tag.get_text(" ", strip=True)
        )
    )

    found = {}

    for tag in candidates:

        text = tag.get_text(" ", strip=True)

        if not text or len(text) > 1800:
            continue

        if not hall_matches(text, target["hall"]):
            continue

        dates = DATE_PATTERN.findall(text)
        times = TIME_PATTERN.findall(text)

        if not dates or not times:
            continue

        booking_links = get_booking_links(
            tag,
            target["url"],
        )

        # A real booking action is required.
        if not booking_links:
            continue

        date_value = dates[0].strip()
        time_value = times[0].strip()

        booking_link = booking_links[0]

        unique_text = (
            f"{target['movie']}|"
            f"{target['hall']}|"
            f"{date_value}|"
            f"{time_value}"
        )

        showtime_id = hashlib.sha256(
            unique_text.lower().encode("utf-8")
        ).hexdigest()

        found[showtime_id] = {
            "movie": target["movie"],
            "hall": target["hall"],
            "date": date_value,
            "time": time_value,
            "link": booking_link,
        }

    return found


# =====================================
# CHECK VOX
# =====================================

def check_target(session, target):

    print(
        f"\nChecking {target['movie']} "
        f"({target['hall']})..."
    )

    try:

        response = session.get(
            target["url"],
            timeout=TIMEOUT,
        )

        if not validate_page(response):
            return None

        print("VOX page loaded successfully.")

        showtimes = extract_showtimes(
            response.text,
            target,
        )

        print(
            f"Detected {len(showtimes)} "
            f"potential bookable showtimes."
        )

        return showtimes

    except requests.RequestException as error:

        print(f"VOX connection error: {error}")

        return None


# =====================================
# PROCESS NEW SHOWTIMES
# =====================================

def process_target(
    session,
    target,
    state,
):

    showtimes = check_target(
        session,
        target,
    )

    # Never treat a failed check as an empty result.
    if showtimes is None:
        return

    movie_key = target["movie"]

    if movie_key not in state:
        state[movie_key] = {}

    previous = state[movie_key]

    new_ids = (
        set(showtimes.keys())
        - set(previous.keys())
    )

    if not new_ids:

        print(
            f"No new bookable tickets for {movie_key}."
        )

        return

    for showtime_id in sorted(new_ids):

        item = showtimes[showtime_id]

        message = (
            "🚨 NEW VOX TICKETS AVAILABLE! 🚨\n\n"
            f"🎬 Movie: {item['movie']}\n"
            f"🎦 Hall: {item['hall']}\n"
            f"📍 Cinema: City Centre Almaza\n"
            f"📅 Date: {item['date']}\n"
            f"🕒 Time: {item['time']}\n\n"
            f"🎟️ Booking link:\n{item['link']}"
        )

        if send_telegram(session, message):

            state[movie_key][showtime_id] = item

            save_state(state)

            print(
                f"New ticket notification sent: "
                f"{item['movie']} - {item['date']} "
                f"{item['time']}"
            )

        else:

            print(
                "Notification failed. "
                "This showtime will be retried "
                "on the next run."
            )

        time.sleep(2)


# =====================================
# MAIN
# =====================================

def main():

    if not TELEGRAM_TOKEN or not CHAT_ID:

        print("Missing Telegram credentials.")
        raise SystemExit(1)

    state = load_state()

    session = requests.Session()
    session.headers.update(HEADERS)

    successful_checks = 0

    try:

        for target in TARGETS:

            before = time.time()

            showtimes = check_target(
                session,
                target,
            )

            if showtimes is not None:

                successful_checks += 1

                movie_key = target["movie"]

                if movie_key not in state:
                    state[movie_key] = {}

                previous = state[movie_key]

                new_ids = (
                    set(showtimes.keys())
                    - set(previous.keys())
                )

                for showtime_id in sorted(new_ids):

                    item = showtimes[showtime_id]

                    message = (
                        "🚨 NEW VOX TICKETS AVAILABLE! 🚨\n\n"
                        f"🎬 Movie: {item['movie']}\n"
                        f"🎦 Hall: {item['hall']}\n"
                        f"📍 Cinema: City Centre Almaza\n"
                        f"📅 Date: {item['date']}\n"
                        f"🕒 Time: {item['time']}\n\n"
                        f"🎟️ Booking link:\n{item['link']}"
                    )

                    if send_telegram(session, message):

                        state[movie_key][showtime_id] = item
                        save_state(state)

                    time.sleep(2)

            elapsed = time.time() - before

            print(
                f"Finished {target['movie']} "
                f"in {elapsed:.1f} seconds."
            )

            time.sleep(2)

        save_state(state)

    finally:

        session.close()

    print("\nMonitoring run completed.")

    print(
        f"Successful page checks: "
        f"{successful_checks}/{len(TARGETS)}"
    )

    if successful_checks == 0:
        raise SystemExit(
            "All VOX checks failed. "
            "No empty results were saved."
        )


if __name__ == "__main__":
    main()
                        
