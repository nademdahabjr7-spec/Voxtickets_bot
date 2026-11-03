import os
import time
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

TARGETS = [
    {
        "movie": "Dune Part Three",
        "hall": "IMAX",
        "query": "site:egy.voxcinemas.com dune imax",
    },
    {
        "movie": "Avengers Doomsday",
        "hall": "MAX",
        "query": "site:egy.voxcinemas.com avengers max",
    },
]


def send_telegram_message(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    print("✅ تم إرسال التنبيه إلى تليجرام بنجاح!")
  except Exception as e:
    print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")


def check_booking():
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/123.0.0.0 Safari/537.36"
      )
  }

  for target in TARGETS:
    movie_name = target["movie"]
    hall_type = target["hall"]
    query = target["query"]
    search_url = f"https://html.duckduckgo.com/html/?q={query}"

    try:
      print(f"⏳ جاري فحص توفر فيلم {movie_name} صالة {hall_type}...")
      response = requests.get(search_url, headers=headers, timeout=15)
      response.raise_for_status()
      page_content = response.text.lower()

      if "vox cinemas" in page_content and (
          "dune" in page_content or "avengers" in page_content
      ):
        # رابط مباشر يبحث عن الفيلم على جوجل عشان يوديك لنتيجة مظبوطة فوراً
        direct_link = (
            f"https://www.google.com/search?q=site:egy.voxcinemas.com+{movie_name}"
        )

        alert_msg = (
            f"🚨 **تنبيه عروض حصرية!** 🚨\n\n"
            f"🎬 الفيلم: **{movie_name}**\n"
            f"🎦 الصالة المستهدفة: **{hall_type}**\n\n"
            f"✨ المؤشرات تدل على ظهور نتائج بحث جديدة على الموقع!\n"
            f"🔗 [اضغط هنا للبحث المباشر عن العرض والحجز]({direct_link})"
        )
        send_telegram_message(alert_msg)
        time.sleep(2)
        print(f"✅ تم رصد تطابق لـ {movie_name} وإرسال التنبيه.")
      else:
        print(f"⏳ فيلم '{movie_name}' صالة '{hall_type}' لسه غير متاح في النتائج.")

    except Exception as e:
      print(f"❌ خطأ أثناء الفحص للفيلم {movie_name}: {e}")

    time.sleep(3)


if __name__ == "__main__":
  check_booking()
    
