import os
import time
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MOVIES_TO_CHECK = ["Dune 3", "Avengers: Doomsday infinity vision"]


def send_telegram_message(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    # زودنا المهلة إلى 20 ثانية عشان الاتصال بتليجرام مايفصلش
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    print("✅ تم إرسال التنبيه إلى تليجرام بنجاح!")
  except Exception as e:
    print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")


def check_booking():
  query = "site:egy.voxcinemas.com Dune 3 OR Avengers Doomsday"
  search_url = f"https://html.duckduckgo.com/html/?q={query}"

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/123.0.0.0 Safari/537.36"
      )
  }

  try:
    print("⏳ جاري فحص توفر الأفلام عبر محركات البحث...")
    response = requests.get(search_url, headers=headers, timeout=15)
    response.raise_for_status()
    page_content = response.text.lower()

    for movie_name in MOVIES_TO_CHECK:
      if movie_name.lower() in page_content:
        alert_msg = (
            f"🚨 **مؤشر حجز جديد!** 🚨\n\n"
            f"فيلم **{movie_name}** ظهر في نتائج موقع فوكس سينما!\n\n"
            f"🔗 [اضغط هنا لزيارة الموقع وحجز التذاكر](https://egy.voxcinemas.com/)"
        )
        send_telegram_message(alert_msg)
        # فاصل زمني صغير بين كل رسالة والثانية عشان تليجرام ميعملش ضغط على الطلب
        time.sleep(2)
        print(f"✅ تم رصد الفيلم: {movie_name} وإرسال التنبيه.")
      else:
        print(f"⏳ فيلم '{movie_name}' لسه مش مفهرس أو متاح للحجز.")

  except Exception as e:
    print(f"❌ خطأ أثناء الفحص: {e}")


if __name__ == "__main__":
  check_booking()
    
