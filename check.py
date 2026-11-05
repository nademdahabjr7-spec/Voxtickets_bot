#!/usr/bin/env python3
import os, re, json, time, hashlib, html, logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
from urllib.parse import urljoin
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
STATE_FILE = "showtimes_state.json"
DEBUG_DIR = "debug"
EGYPT_TZ = ZoneInfo("Africa/Cairo")
BASE_URL = "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza"

TARGETS = [
    {"movie": "Dune: Part Three", "match": ["dune part three"], "hall": "IMAX", "hall_match": ["imax"], "url": BASE_URL + "&m=dune-part-three"},
    {"movie": "Avengers: Doomsday (Infinity Vision)", "match": ["avengers doomsday", "avengers doomsday infinity vision"], "hall": "Infinity Vision", "hall_match": ["infinity vision"], "url": BASE_URL + "&m=avengers-doomsday-infinity-vision"}
]

TIME_PATTERN = re.compile(r"(?<!\d)(?:(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:am|pm)|(?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)", re.I)
ISO_DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{1,2}-\d{1,2})\b")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("VOX-Monitor")

def now(): return datetime.now(EGYPT_TZ)
def normalize(v): return re.sub(r"[^a-z0-9]+", " ", (v or "").lower().replace("&", " and ")).strip()
def safe_text(el):
    try: return el.text.strip()
    except StaleElementReferenceException: return ""

def parse_date(v):
    if not v: return None
    m = ISO_DATE_PATTERN.search(str(v).strip())
    if m:
        try: return date.fromisoformat(m.group(1)).isoformat()
        except ValueError: pass
    return None

def normalize_time(v):
    v = v.strip().lower().replace(" ", "")
    if re.search(r"(am|pm)$", v):
        try: return datetime.strptime(v, "%I:%M%p").strftime("%I:%M %p").lstrip("0")
        except ValueError: return v
    try: return datetime.strptime(v, "%H:%M").strftime("%H:%M")
    except ValueError: return v

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except: return {}

def save_state(s):
    temp = STATE_FILE + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=2)
        os.replace(temp, STATE_FILE)
    except: pass

def send_telegram(msg, url=None):
    if not TELEGRAM_TOKEN or not CHAT_ID: return False
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
    if url: payload["reply_markup"] = {"inline_keyboard": [[{"text": "🎟 Open VOX Booking", "url": url}]]}
    for _ in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload, timeout=20)
            if r.json().get("ok"): return True
        except: time.sleep(2)
    return False

def new_browser():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    return driver

def load_vox_page(driver, url):
    for _ in range(3):
        try:
            driver.get(url)
            WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
            time.sleep(3)
            return True
        except: time.sleep(3)
    return False

def extract_target_showtimes(driver, target):
    results = {}
    articles = driver.find_elements(By.CSS_SELECTOR, "article.movie-compare")
    for article in articles:
        try:
            titles = article.find_elements(By.CSS_SELECTOR, "h2")
            if not titles or not any(n in normalize(safe_text(titles[0])) for n in target["match"]): continue
            hall_groups = article.find_elements(By.CSS_SELECTOR, "div.dates ol.showtimes > li")
            for hg in hall_groups:
                strong = hg.find_elements(By.TAG_NAME, "strong")
                hall = safe_text(strong[0]) if strong else safe_text(hg)
                if not any(h in normalize(hall) for h in target["hall_match"]): continue
                
                show_date = None
                try:
                    dt_attr = driver.execute_script("let el = arguments[0]; for(let i=0; el && i<4; i++, el=el.parentElement){let d=el.getAttribute('data-date'); if(d) return d;} return null;", hg)
                    show_date = parse_date(dt_attr)
                except: pass

                items = hg.find_elements(By.CSS_SELECTOR, "ol > li")
                for item in items:
                    links = item.find_elements(By.CSS_SELECTOR, "a.showtime")
                    link = links[0] if links else None
                    text = safe_text(link) if link else safe_text(item)
                    match = TIME_PATTERN.search(text)
                    if not match: continue
                    showtime = normalize_time(match.group(0))
                    href = link.get_attribute("href") if link else None
                    booking_open = bool(href and href.startswith("http"))
                    
                    identity = "|".join([target["movie"], target["hall"], show_date or "unknown", showtime.lower(), item.get("data-id", "")])
                    item_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                    results[item_id] = {"movie": target["movie"], "hall": target["hall"], "date": show_date, "time": showtime, "booking_open": booking_open, "link": urljoin(target["url"], href) if href else target["url"]}
        except: pass
    return results

def process_results(results, state):
    for item_id, item in results.items():
        prev = state.get(item_id, {})
        if not isinstance(prev, dict): prev = {}
        if not prev.get("showtime_alerted"):
            msg = f"🆕 <b>NEW VOX SHOWTIME!</b>\n\n🎬 {html.escape(item['movie'])}\n🎦 Hall: {html.escape(item['hall'])}\n🕒 Time: {html.escape(item['time'])}"
            if send_telegram(msg, item["link"]):
                prev["showtime_alerted"] = True
                state[item_id] = prev
                save_state(state)
            time.sleep(1)
        if item["booking_open"] and not prev.get("booking_alerted"):
            msg = f"🎟 <b>VOX BOOKING AVAILABLE!</b>\n\n🎬 {html.escape(item['movie'])}\n🎦 Hall: {html.escape(item['hall'])}\n🕒 Time: {html.escape(item['time'])}"
            if send_telegram(msg, item["link"]):
                prev["booking_alerted"] = True
                state[item_id] = prev
                save_state(state)
            time.sleep(1)

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    state = load_state()
    driver = None
    success = 0
    try:
        driver = new_browser()
        for target in TARGETS:
            if load_vox_page(driver, target["url"]):
                success += 1
                process_results(extract_target_showtimes(driver, target), state)
        if success > 0:
            send_telegram(f"🟢 <b>VOX Monitor Status</b>\n\nChecked successfully at {now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        log.error(str(e))
    finally:
        if driver: driver.quit()
    save_state(state)

if __name__ == "__main__":
    main()
            
