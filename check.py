import os
import requests

# جلب البيانات
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


def send_test_message():
    # التأكد من كتابة الرابط بطريقة سليمة ومباشرة
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": "🚨 البوت شغال يا معلم وتم الاتصال بنجاح!",
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ خطأ: {e}")


if __name__ == "__main__":
    send_test_message()
    
