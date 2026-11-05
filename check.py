#!/usr/bin/env python3
# VOX Cinemas Monitor -> Telegram
# Dune: Part Three (IMAX)
# Avengers: Doomsday (Infinity Vision)

import os
import re
import json
import time
import hashlib
import html
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)

# =====================================
# SETTINGS
# =====================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

STATE_FILE = "showtimes_state.json"
DEBUG_DIR = "debug"

EGYPT_TZ = ZoneInfo("Africa/Cairo")

BASE_URL = (
    "https://egy.voxcinemas.com/showtimes"
    "?c=city-centre-almaza"
)

TARGETS = [
    {
        "movie": "Dune: Part Three",
        "match": ["dune part three"],
        "hall": "IMAX",
        "hall_match": ["imax"],
        "url": BASE_URL + "&m=dune-part-three",
    },
    {
        "movie": "Avengers: Doomsday (Infinity Vision)",
        "match": [
            "avengers doomsday",
            "avengers doomsday infinity vision",
        ],
        "hall": "Infinity Vision",
        "hall_match": ["infinity vision"],
        "url": BASE_URL + "&m=avengers-doomsday-infinity-vision",
    },
]

TIME_PATTERN = re.compile(
    r"(?<!\d)(?:"
    r"(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:am|pm)"
    r"|(?:[01]?\d|2[0-3]):[0-5]\d"
    r")(?!\d)",
    re.I,
)

ISO_DATE_PATTERN = re.compile(
    r"\b(20\d{2}-\d{1,2}-\d{1,2})\b"
)

HUMAN_DATE_PATTERN = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?"
    r"\s*(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"(?:\s+(20\d{2}))?\b",
    re.I,
)

MONTH_DATE_PATTERN = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b",
    re.I,
)

# =====================================
# LOGGING
# =====================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("VOX-Monitor")


def now():
    return datetime.now(EGYPT_TZ)


# =====================================
# HELPERS
# =====================================

def normalize(value):
    value = (value or "").lower()
    value = value.replace("&", "
    
