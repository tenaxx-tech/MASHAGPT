import os
import sys

# ------------------------------------------------------------------
# Telegram Bot
# ------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ Ошибка: TELEGRAM_TOKEN не задан")
    sys.exit(1)

# ------------------------------------------------------------------
# MASHA (предполагаемая интеграция)
# ------------------------------------------------------------------
MASHA_API_KEY = os.getenv("MASHA_API_KEY")
if not MASHA_API_KEY:
    print("❌ Ошибка: MASHA_API_KEY не задан")
    sys.exit(1)

MASHA_BASE_URL = os.getenv("MASHA_BASE_URL", "https://api.masha.example.com")

# ------------------------------------------------------------------
# DonationAlerts
# ------------------------------------------------------------------
DA_CLIENT_ID = os.getenv("DA_CLIENT_ID")
if not DA_CLIENT_ID:
    print("❌ Ошибка: DA_CLIENT_ID не задан")
    sys.exit(1)

DA_CLIENT_SECRET = os.getenv("DA_CLIENT_SECRET")
if not DA_CLIENT_SECRET:
    print("❌ Ошибка: DA_CLIENT_SECRET не задан")
    sys.exit(1)

DA_REDIRECT_URI = os.getenv("DA_REDIRECT_URI", "https://your-domain.ru/callback")
DA_SECRET_KEY = os.getenv("DA_SECRET_KEY")
if not DA_SECRET_KEY:
    print("❌ Ошибка: DA_SECRET_KEY не задан")
    sys.exit(1)

DA_USERNAME = os.getenv("DA_USERNAME", "designdmitriy")   # не секрет, можно дефолт

# ------------------------------------------------------------------
# DeepSeek
# ------------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("❌ Ошибка: DEEPSEEK_API_KEY не задан")
    sys.exit(1)
