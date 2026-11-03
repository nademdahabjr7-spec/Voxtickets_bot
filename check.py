import os
import time
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

TARGETS = [
    {
        "movie": "Dune Part Three",
        "hall": "IMAX",
        "url": (
            "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=dune-part-three"
        ),
    },
    {
        "movie": "Avengers Doomsday",
        "hall": "MAX",
        "url": (
            "https://egy.voxcinemas.com/showtimes?c=city-centre-almaza&m=avengers-doomsday-infinity-vision"
        ),
    },
]


def send_telegram_with_button(message, url_link):
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

  # زرار تفاعلي يفتح صفحة الحجز واختيار الكراسي فوراً
  reply_markup = {
      "inline_keyboard": [[
          {"text": "🎟️ فتح الجدول واختيار الكراسي مباشرة", "url": url_link}
      ]]
  }

  payload = {
      "chat_id": CHAT_ID,
      "text": message,
      "parse_mode": "Markdown",
      "reply_markup": reply_markup,
  }

  try:
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    print("✅ تم إرسال التنبيه التفاعلي إلى تليجرام بنجاح!")
  except Exception as e:
    print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")


def check_booking():
  # Headers قوية عشان الموقع ما يعتبيرناش روبوت ويقفل الطلب
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/123.0.0.0 Safari/537.36"
      ),
      "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
  }

  for target in TARGETS:
    movie_name = target["movie"]
    hall_type = target["hall"]
    page_url = target["url"]

    try:
      print(f"⏳ جاري فحص صفحة فوكس لفيلم {movie_name} صالة {hall_type}...")
      response = requests.get(page_url, headers=headers, timeout=15)

      # لو الموقع فتح ورد بنجاح
      if response.status_code == 200:
        page_content = response.text.lower()

        # هنا بنفحص لو الصفحة فيها كلمات تدل إن المواعيد نزلت فعلاً
        # (مثل أسعار، أوقات، أو جداول عرض بدل صفحة "قريباً")
        if "showtimes" in page_content or "book" in page_content:
          # نتأكد إنها مش مجرد كلمة عادية في صفحة "قريباً"، ممكن نضيف شروط تانية لو حابب
          alert_msg = (
              f"🚨 **المواعيد نزلت رسمياً على موقع فوكس!** 🚨\n\n"
              f"🎬 الفيلم: **{movie_name}**\n"
              f"🎦 الصالة: **{hall_type}**\n"
              f"📍 سينما: **سيتي سنتر ألماظة**\n\n"
              f"👇 اضغط على الزر أدناه لفتح الجدول واختيار الكراسي فوراً:"
          )
          send_telegram_with_button(alert_msg, page_url)
          time.sleep(2)
          print(f"✅ تم رصد المواعيد الحقيقية لـ {movie_name} وإرسال التنبيه.")
        else:
          print(
              f"⏳ صفحة '{movie_name}' صالة '{hall_type}' لسه مانزلش جدولها"
              " (قريباً)."
          )
      else:
        print(f"⚠️ موقع فوكس رد بكود غير متوقع: {response.status_code}")

    except Exception as e:
      print(f"❌ خطأ أثناء الاتصال بموقع فوكس للفيلم {movie_name}: {e}")

    time.sleep(3)


if __name__ == "__main__":
  check_booking()
    
