import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Обязательные переменные
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN не задан")
    sys.exit(1)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("❌ DEEPSEEK_API_KEY не задан")
    sys.exit(1)

# Masha для изображений (опционально, если нужно)
MASHA_API_KEY = os.getenv("MASHA_API_KEY")
MASHA_BASE_URL = os.getenv("MASHA_BASE_URL", "https://openapi.masha.ai/v1")

# Опциональные
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 8080))
