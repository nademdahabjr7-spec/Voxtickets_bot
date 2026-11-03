import json
import os
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ===== الإعدادات =====
URL = "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza"  # رابط صفحة السينما
MOVIE_LINK_SELECTOR = 'a[href*="/movie-details/"]'  # طريقة الوصول لروابط الأفلام في الموقع
WATCHED_MOVIES = [
    "Avengers Doomsday",
    "Dune part three",
]
TOKEN = os.environ["TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
FILE = "seen.json"


def normalize(text):
    """توحيد شكل الكتابة عشان المقارنة تبقى أدق"""
    text = text.strip().lower()
    for old, new in [("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")]:
        text = text.replace(old, new)
    return text


def is_watched(name):
    n = normalize(name)
    return any(normalize(w) in n for w in WATCHED_MOVIES)


def load_seen():
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def get_watched_movies():
    html = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
    soup = BeautifulSoup(html, "html.parser")

    movies = {}
    for a in soup.select(MOVIE_LINK_SELECTOR):
        name = (a.get("title") or a.get_text(strip=True) or "").strip()
        if name and is_watched(name):
            movies[urljoin(URL, a["href"])] = name
    return movies


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=20,
    )
    r.raise_for_status()


def main():
    try:
        movies = get_watched_movies()
    except requests.RequestException as e:
        print("فشل تحميل الصفحة:", e)
        sys.exit(1)

    print("لقيت", len(movies), "من الأفلام اللي بتتابعها")

    seen = load_seen()
    new_movies = {url: name for url, name in movies.items() if url not in seen}

    if new_movies:
        lines = ["🎬 فيلم من اللي بتتابعه بقى متاح:", ""]
        for url, name in new_movies.items():
            lines.append(f"• {name}\n{url}")
        send_telegram("\n".join(lines))
        print("اتبعت", len(new_movies), "إشعار")
    else:
        print("مفيش جديد")

    seen.update(new_movies)
    save_seen(seen)


if __name__ == "__main__":
    main()
