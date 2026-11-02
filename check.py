import requests
import json
import os
import sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup

URL = "https://cfc.scenecinemas.com/home"
TOKEN = os.environ["TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
FILE = "seen.json"


def load_seen():
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def get_movies():
    html = requests.get(
        URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"}
    ).text
    soup = BeautifulSoup(html, "html.parser")

    movies = {}
    for a in soup.select('a[href*="/movie-details/"]'):
        name = (a.get("title") or a.get_text(strip=True) or "").strip()
        if name:
            # نحول الرابط النسبي لرابط كامل عشان يبقى مفتاح ثابت
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
        movies = get_movies()
    except requests.RequestException as e:
        print("فشل تحميل الصفحة:", e)
        sys.exit(1)

    print("لقيت", len(movies), "فيلم")

    seen = load_seen()
    new_movies = {url: name for url, name in movies.items() if url not in seen}

    if new_movies:
        lines = ["🎬 أفلام جديدة في سينيما سيتي:", ""]
        for url, name in new_movies.items():
            lines.append(f"• {name}\n{url}")
        send_telegram("\n".join(lines))
        print("اتبعت", len(new_movies), "فيلم جديد")
    else:
        print("مفيش أفلام جديدة")

    seen.update(movies)
    save_seen(seen)


if __name__ == "__main__":
    main()
