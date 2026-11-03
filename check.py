
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
# MOVIES TO MONITOR
# =====================================

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "hall": "IMAX",
        "url": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three"
    },
    {
        "movie": "Avengers: Doomsday",
        "hall": "MAX",
        "url": "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=avengers-doomsday-infinity-vision"
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
# LOAD AND SAVE MONITORING DATA
# =====================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        print("⚠️ Could not read saved state.")
        return {}


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    os.replace(temp_file, STATE_FILE)


# =====================================
# TELEGRAM NOTIFICATIONS
# =====================================

def send_telegram(session, message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    try:
        response = session.post(
            url,
            json=payload,
            timeout=20
        )

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
# HALL DETECTION
# =====================================

def hall_matches(text, hall):

    if hall == "IMAX":
        return bool(re.search(r"\bIMAX\b", text, re.I))

    return bool(re.search(r"\bMAX\b", text, re.I))


# =====================================
# EXTRACT ACTUAL SHOWTIME CANDIDATES
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
        key=lambda tag: len(tag.get_text(" ", strip=True))
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

        booking_links = []

        for link in tag.find_all("a", href=True):

            href = urljoin(
                target["url"],
                link["href"]
            )

            label = link.get_text(" ", strip=True)

            if (
                BOOKING_PATTERN.search(label)
                or "book" in href.lower()
                or "seat" in href.lower()
            ):
                booking_links.append(href)

        if not BOOKING_PATTERN.search(text) and not booking_links:
            continue

        date_value = dates[0].strip()
        time_value = times[0].strip()

        booking_link = (
            booking_links[0]
            if booking_links
            else target["url"]
        )

        unique_text = (
            target["movie"] + "|" +
            target["hall"] + "|" +
            date_value + "|" +
            time_value
        )

        showtime_id = hashlib.sha256(
            unique_text.lower().encode("utf-8")
        ).hexdigest()

        found[showtime_id] = {
            "movie": target["movie"],
            "hall": target["hall"],
            "date": date_value,
            "time": time_value,
            "link": booking_link
        }

    return found


# =====================================
# CHECK VOX CINEMAS
# =====================================

def check_target(session, target):

    print(
        f"\n⏳ Checking {target['movie']} "
        f"({target['hall']})..."
    )

    try:

        response = session.get(
            target["url"],
            timeout=25
        )

        response.raise_for_status()

        html = response.text

        if len(html) < 500:
            print("⚠️ Invalid or incomplete page.")
            return None

        blocked_markers = [
            "access denied",
            "errors.edgesuite.net",
            "akamai reference"
        ]

        if any(
            marker in html.lower()
            for marker in blocked_markers
        ):
            print("⚠️ VOX access denied.")
            return None

        showtimes = extract_showtimes(
            html,
            target
        )

        print(
            f"🎯 Found {len(showtimes)} "
            f"potential showtimes."
        )

        return showtimes

    except requests.RequestException as error:

        print(f"❌ VOX connection error: {error}")
        return None


# =====================================
# MAIN MONITORING SYSTEM
# =====================================

def main():

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Missing Telegram credentials.")
        return

    state = load_state()

    session = requests.Session()
    session.headers.update(HEADERS)

    for target in TARGETS:

        showtimes = check_target(
            session,
            target
        )

        if showtimes is None:
            continue

        movie_key = target["movie"]

        if movie_key not in state:
            state[movie_key] = {}

        previous = state[movie_key]

        new_ids = (
            set(showtimes.keys())
            - set(previous.keys())
        )

        for showtime_id in new_ids:

            item = showtimes[showtime_id]

            message = (
                "🚨 NEW VOX SHOWTIME DETECTED!\n\n"
                f"🎬 Movie: {item['movie']}\n"
                f"🎦 Hall: {item['hall']}\n"
                f"📅 Date: {item['date']}\n"
                f"🕒 Time: {item['time']}\n\n"
                "🎟️ Booking link:\n"
                f"{item['link']}"
            )

            if send_telegram(session, message):

                state[movie_key][showtime_id] = item

                save_state(state)

            time.sleep(2)

        if not new_ids:
            print(
                f"⏳ No new showtimes for {movie_key}."
            )

        time.sleep(3)

    save_state(state)

    session.close()

    print("\n✅ Monitoring completed.")


# =====================================
# START
# =====================================

if __name__ == "__main__":
    main()
    
