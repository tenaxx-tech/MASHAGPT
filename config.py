import os
import sys
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN не задан")
    sys.exit(1)

MASHA_API_KEY = os.getenv("MASHA_API_KEY")
if not MASHA_API_KEY:
    print("❌ MASHA_API_KEY не задан")
    sys.exit(1)

MASHA_BASE_URL = "https://api.mashagpt.ru/v1"
# MASHA_BASE_URL = os.getenv("MASHA_BASE_URL", "https://api.mashagpt.ru/v1")

DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 8080))

# ---------- Robokassa ----------
ROBOKASSA_LOGIN = os.getenv("ROBOKASSA_LOGIN")
ROBOKASSA_PASSWORD1 = os.getenv("ROBOKASSA_PASSWORD1")
ROBOKASSA_PASSWORD2 = os.getenv("ROBOKASSA_PASSWORD2")
ROBOKASSA_TEST_MODE = os.getenv("ROBOKASSA_TEST_MODE", "True").lower() == "true"
ROBOKASSA_RESULT_URL = os.getenv("ROBOKASSA_RESULT_URL")
ROBOKASSA_SUCCESS_URL = os.getenv("ROBOKASSA_SUCCESS_URL")
ROBOKASSA_FAIL_URL = os.getenv("ROBOKASSA_FAIL_URL")

if not ROBOKASSA_LOGIN:
    print("❌ ROBOKASSA_LOGIN не задан в .env")
    sys.exit(1)
