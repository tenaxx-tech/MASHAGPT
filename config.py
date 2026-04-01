import os
import sys

# ------------------------------------------------------------------
# Telegram Bot (обязательная)
# ------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ Ошибка: TELEGRAM_TOKEN не задан")
    sys.exit(1)

# ------------------------------------------------------------------
# Felo AI (опционально, не используется в текущем коде)
# ------------------------------------------------------------------
FELO_API_KEY = os.getenv("FELO_API_KEY")
FELO_API_URL = os.getenv("FELO_API_URL", "https://openapi.felo.ai/v2/chat")

# ------------------------------------------------------------------
# Replicate (опционально)
# ------------------------------------------------------------------
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# ------------------------------------------------------------------
# OpenAI (опционально)
# ------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ------------------------------------------------------------------
# MASHA (обязательная, так как используется в generate_text)
# ------------------------------------------------------------------
MASHA_API_KEY = os.getenv("MASHA_API_KEY")
if not MASHA_API_KEY:
    print("❌ Ошибка: MASHA_API_KEY не задан")
    sys.exit(1)

MASHA_BASE_URL = os.getenv("MASHA_BASE_URL", "https://api.masha.example.com")

# ------------------------------------------------------------------
# DonationAlerts (опционально, не используется в текущем боте)
# ------------------------------------------------------------------
DA_CLIENT_ID = os.getenv("DA_CLIENT_ID")
DA_CLIENT_SECRET = os.getenv("DA_CLIENT_SECRET")
DA_REDIRECT_URI = os.getenv("DA_REDIRECT_URI", "https://your-domain.ru/callback")
DA_SECRET_KEY = os.getenv("DA_SECRET_KEY")
DA_USERNAME = os.getenv("DA_USERNAME", "designdmitriy")

# ------------------------------------------------------------------
# DeepSeek (обязательная, если используется в коде — а у вас импорт есть)
# ------------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("❌ Ошибка: DEEPSEEK_API_KEY не задан")
    sys.exit(1)

# ------------------------------------------------------------------
# Общие настройки
# ------------------------------------------------------------------
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 8080))
