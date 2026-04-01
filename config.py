import os
import sys
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN не задан")
    sys.exit(1)

MASHA_API_KEY = os.getenv("MASHA_API_KEYS")
if not MASHA_API_KEY:
    print("❌ MASHA_API_KEY не задан")
    sys.exit(1)

MASHA_BASE_URL = "https://api.mashagpt.ru/v1"   # фиксированный правильный URL
# Если хотите использовать переменную окружения, раскомментируйте следующую строку:
# MASHA_BASE_URL = os.getenv("MASHA_BASE_URL", "https://api.mashagpt.ru/v1")

DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 8080))
