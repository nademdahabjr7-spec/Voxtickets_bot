#!/usr/bin/env python3
"""
Vox Cinemas (City Centre Almaza) showtime monitor -> Telegram alerts.

Modes:
  python vox_showtimes_monitor.py                 loop forever (every POLL_SECONDS, default 300)
  python vox_showtimes_monitor.py --once          one check, then exit (Task Scheduler / cron)
  python vox_showtimes_monitor.py --test-file page.html --target 0
                                                  parse a saved page offline (0 = Dune, 1 = Avengers)

Environment variables:
  TELEGRAM_TOKEN   bot token (live runs)
  CHAT_ID          Telegram chat id (live runs)
  POLL_SECONDS     seconds between checks in loop mode (default 300)
  NOTIFY_EXISTING  1 = alert about showtimes already listed on the first run (default)
                   0 = just remember them, alert only when new ones appear later
  DUMP_HTML        1 = save every fetched page as debug_<n>.html next to this script
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# إستخدام المسار المطلق لضمان عمل الـ State بشكل آمن مع Cron
BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "seen_showtimes.json"
VOX_URL = "https://egy.voxcinemas.com/showtimes/city-centre-almaza"

# إعداد التسجيل بدون إظهار الـ Token
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# قراءة الإعدادات من البيئة
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", 300))
NOTIFY_EXISTING = int(os.getenv("NOTIFY_EXISTING", 1))
DUMP_HTML = int(os.getenv("DUMP_HTML", 0))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def send_telegram_alert(message: str) -> bool:
    """إرسال التنبيهات مع إخفاء الـ Token من الـ Logs لأمان أكثر."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("TELEGRAM_TOKEN or CHAT_ID is not set. Skipping Telegram alert.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Telegram alert sent successfully.")
        return True
    except requests.exceptions.RequestException as e:
        # طباعة الخطأ بدون إظهار الـ Token
        safe_err = str(e).replace(TELEGRAM_TOKEN, "*****")
        logger.error(f"Failed to send Telegram alert: {safe_err}")
        return False

def fetch_showtimes_page() -> str:
    """جلب صفحة المواعيد مباشرة بدون DuckDuckGo fallback."""
    logger.info(f"Fetching showtimes from {VOX_URL}...")
    try:
        response = requests.get(VOX_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        html_content = response.text

        if DUMP_HTML:
            dump_path = BASE_DIR / "debug_0.html"
            dump_path.write_text(html_content, encoding="utf-8")
            logger.info(f"Saved HTML dump to {dump_path}")

        return html_content
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Vox page: {e}")
        return ""

def parse_showtimes(html_content: str) -> list[dict]:
    """
    تحليل الصفحة مع ربط كل ساعة بأحدث تاريخ وأحدث اسم قاعة فوقها في الـ Block،
    ودعم الأسماء الحساسة لحالة الأحرف (MAX / Infinity Vision / Avengers).
    """
    soup = BeautifulSoup(html_content, "html.parser")
    showtimes_list = []
    
    current_date = "Today"
    current_hall = "Standard"
    
    # محاذاة العثور على
    
