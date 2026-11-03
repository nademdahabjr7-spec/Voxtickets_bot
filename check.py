import os
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "🚨 تجربة ناجح يا معلم! البوت شغال وبيقدر يبعت رسائل.",
    "parse_mode": "Markdown",
}

response = requests.post(url, json=payload)
print(response.text)
