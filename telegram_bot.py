import asyncio
import io
import json
import logging
from typing import List, Tuple

import aiohttp
from aiohttp import web
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, PreCheckoutQueryHandler,
    CallbackQueryHandler
)

from config import TELEGRAM_TOKEN, MASHA_API_KEY, MASHA_BASE_URL
from database import (
    init_db, save_message, get_history, clear_history, update_user_activity,
    get_user_balance, add_balance, deduct_balance,
    get_weekly_image_count, increment_weekly_image_count
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------- Состояния -------------------
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, EDIT_GEN, AUDIO_GEN, AVATAR_GEN, DIALOG, AWAIT_PROMPT = range(9)

# ------------------- Цены моделей -------------------
MODEL_PRICES = {
    "gpt-5-nano": 0, "gpt-5-mini": 0, "gpt-4o-mini": 0, "gpt-4.1-nano": 0,
    "deepseek-chat": 0, "deepseek-reasoner": 0,
    "grok-4-1-fast-reasoning": 0, "grok-4-1-fast-non-reasoning": 0, "grok-3-mini": 0,
    "gemini-2.0-flash": 0, "gemini-2.0-flash-lite": 0, "gemini-2.5-flash-lite": 0,
    "gpt-5.4": 15, "gpt-5.1": 10, "gpt-5": 10, "gpt-4.1": 8, "gpt-4o": 10,
    "o3-mini": 4.4, "o3": 40, "o1": 60,
    "claude-haiku-4-5": 5, "claude-sonnet-4-5": 15, "claude-opus-4-5": 25,
    "gemini-3-flash": 3, "gemini-2.5-pro": 10, "gemini-3-pro": 16, "gemini-3-pro-image": 12,
    "z-image": 0, "grok-imagine-text-to-image": 0, "codeplugtech-face-swap": 0,
    "cdlingram-face-swap": 0, "recraft-crisp-upscale": 0, "recraft-remove-background": 0,
    "topaz-image-upscale": 0, "flux-2": 0, "qwen-edit-multiangle": 0, "nano-banana-2": 0,
    "nano-banana-pro": 0, "midjourney": 0, "gpt-image-1-5-text-to-image": 0,
    "gpt-image-1-5-image-to-image": 0, "ideogram-v3-reframe": 0,
    "grok-imagine-text-to-video": 1, "wan-2-6-text-to-video": 3, "wan-2-5-text-to-video": 3,
    "wan-2-6-image-to-video": 3, "wan-2-6-video-to-video": 3, "wan-2-5-image-to-video": 3,
    "sora-2-text-to-video": 3, "sora-2-image-to-video": 3, "veo-3-1": 5,
    "kling-2-6-text-to-video": 6, "kling-v2-5-turbo-pro": 6, "kling-2-6-image-to-video": 6,
    "kling-v2-5-turbo-image-to-video-pro": 5, "sora-2-pro-text-to-video": 5,
    "sora-2-pro-image-to-video": 5, "sora-2-pro-storyboard": 7, "hailuo-2-3": 4,
    "minimax-video-01-director": 4, "seedance-v1-pro-fast": 30, "kling-2-6-motion-control": 6,
    "elevenlabs-tts-multilingual-v2": 0, "elevenlabs-tts-turbo-2-5": 0,
    "elevenlabs-text-to-dialogue-v3": 0, "elevenlabs-sound-effect-v2": 5,
    "kling-v1-avatar-pro": 16, "kling-v1-avatar-standard": 8, "infinitalk-from-audio": 1.1,
    "wan-2-2-animate-move": 0.75, "wan-2-2-animate-replace": 0.75,
}

# ------------------- Клавиатуры (полные, но сокращены для краткости) -------------------
# (здесь вставьте все функции get_*_keyboard из предыдущего кода, они корректны)
# Для экономии места не копирую, но они должны быть.

# ------------------- Вспомогательные функции -------------------
async def send_long_message(update: Update, text: str):
    if not text:
        return
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i+4096])

async def create_task(model: str, payload: dict, retries=3):
    url = f"{MASHA_BASE_URL}/tasks/{model}"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 429:
                        wait = 2 ** attempt
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("id")
        except Exception as e:
            logger.error(f"Ошибка создания задачи {model}: {e}")
            if attempt == retries - 1:
                return None
            await asyncio.sleep(2)
    return None

async def get_task_status(task_id: str):
    url = f"{MASHA_BASE_URL}/tasks/{task_id}"
    headers = {"x-api-key": MASHA_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json()
                resp.raise_for_status()
                return data
    except Exception as e:
        logger.error(f"Ошибка получения статуса {task_id}: {e}")
        return None

async def wait_for_task(task_id: str, timeout=180):
    start = asyncio.get_event_loop().time()
    while True:
        data = await get_task_status(task_id)
        if not data:
            return None
        status = data.get("status")
        if status == "COMPLETED":
            return data
        elif status == "FAILED":
            logger.error(f"Задача {task_id} провалилась: {data.get('errorMessage')}")
            return None
        await asyncio.sleep(2)
        if asyncio.get_event_loop().time() - start > timeout:
            return None

async def masha_text_generate(prompt: str, history: List[Tuple[str, str]], model: str) -> str:
    messages = []
    for role, content in history[-5:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    url = f"{MASHA_BASE_URL}/chat/completions"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 1024,
        "temperature": 1.0
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Masha error {resp.status}: {error_text}")
            data = await resp.json()
            content = None
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content")
            if not content:
                content = data.get("result") or data.get("output")
            if not content:
                return ""
            return content

async def masha_media_generate(model: str, payload: dict) -> bytes:
    task_id = await create_task(model, payload)
    if not task_id:
        raise Exception("Не удалось создать задачу")
    result = await wait_for_task(task_id)
    if not result:
        raise Exception("Не удалось получить результат")
    outputs = result.get("output", [])
    if not outputs:
        raise Exception("Нет output в ответе")
    media_url = outputs[0].get("url")
    if not media_url:
        raise Exception("Нет URL в ответе")
    async with aiohttp.ClientSession() as session:
        async with session.get(media_url) as resp:
            return await resp.read()

def build_payload(model: str, prompt: str = None, image_url: str = None) -> dict:
    # Обработка face-swap
    if model in ("codeplugtech-face-swap", "cdlingram-face-swap"):
        if image_url and " " in image_url:
            urls = image_url.split()
            return {"inputImage": urls[0], "swapImage": urls[1]}
        return None
    # Обработка qwen
    if model == "qwen-edit-multiangle":
        if not prompt or not image_url:
            return None
        return {"prompt": prompt, "image": image_url}
    # Стандартные payloads
    payloads = {
        "nano-banana-2": {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"},
        "nano-banana-pro": {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"},
        "z-image": {"prompt": prompt, "aspectRatio": "1:1"},
        "grok-imagine-text-to-image": {"prompt": prompt, "aspectRatio": "1:1"},
        "flux-2": {"prompt": prompt, "model": "pro", "aspectRatio": "1:1", "resolution": "1K"},
        "midjourney": {"taskType": "mj_txt2img", "prompt": prompt, "aspectRatio": "1:1", "speed": "fast"},
        "gpt-image-1-5-text-to-image": {"prompt": prompt, "aspectRatio": "1:1", "quality": "medium"},
        "recraft-remove-background": {"imageUrl": image_url} if image_url else None,
        "gpt-image-1-5-image-to-image": {"prompt": prompt, "inputUrls": [image_url]} if image_url else None,
        "ideogram-v3-reframe": {"imageUrl": image_url, "imageSize": "square", "renderingSpeed": "BALANCED"} if image_url else None,
        "recraft-crisp-upscale": {"imageUrl": image_url} if image_url else None,
        "topaz-image-upscale": {"imageUrl": image_url, "upscaleFactor": "2"} if image_url else None,
        "grok-imagine-text-to-video": {"prompt": prompt, "aspectRatio": "3:2", "mode": "normal"},
        "wan-2-6-text-to-video": {"prompt": prompt, "duration": "5", "resolution": "1080p"},
        "wan-2-5-text-to-video": {"prompt": prompt, "duration": "5", "aspectRatio": "16:9", "resolution": "1080p"},
        "wan-2-6-image-to-video": {"prompt": prompt, "imageUrls": [image_url]} if image_url else None,
        "wan-2-6-video-to-video": {"prompt": prompt, "videoUrls": [image_url]} if image_url else None,
        "wan-2-5-image-to-video": {"prompt": prompt, "imageUrl": image_url} if image_url else None,
        "sora-2-text-to-video": {"prompt": prompt, "aspectRatio": "landscape", "duration": "10", "removeWatermark": True},
        "sora-2-image-to-video": {"prompt": prompt, "imageUrls": [image_url]} if image_url else None,
        "veo-3-1": {"prompt": prompt, "model": "veo3_fast", "aspectRatio": "16:9"},
        "kling-2-6-text-to-video": {"prompt": prompt, "aspectRatio": "16:9", "duration": "5", "sound": False},
        "kling-v2-5-turbo-pro": {"prompt": prompt, "aspectRatio": "16:9", "duration": "5", "cfgScale": 0.5},
        "kling-2-6-image-to-video": {"prompt": prompt, "imageUrl": image_url, "duration": "5", "sound": False} if image_url else None,
        "kling-v2-5-turbo-image-to-video-pro": {"prompt": prompt, "imageUrl": image_url, "duration": "5", "cfgScale": 0.5} if image_url else None,
        "sora-2-pro-text-to-video": {"prompt": prompt, "aspectRatio": "landscape", "duration": "10", "size": "high"},
        "sora-2-pro-image-to-video": {"prompt": prompt, "imageUrls": [image_url], "duration": "10", "resolution": "1080p"} if image_url else None,
        "sora-2-pro-storyboard": {"duration": "15", "shots": [{"scene": prompt, "duration": 5}]},
        "hailuo-2-3": {"prompt": prompt, "duration": "6", "resolution": "768P", "variant": "standard"},
        "minimax-video-01-director": {"prompt": prompt, "promptOptimizer": True},
        "seedance-v1-pro-fast": {"prompt": prompt, "imageUrl": image_url, "resolution": "720p", "duration": "5"} if image_url else None,
        "kling-2-6-motion-control": {"prompt": prompt, "imageUrls": [image_url] if image_url else None, "characterOrientation": "image", "duration": 5},
        "elevenlabs-tts-multilingual-v2": {"text": prompt, "voice": "Rachel", "stability": 0.5, "similarityBoost": 0.75, "speed": 1.0, "languageCode": "ru"},
        "elevenlabs-tts-turbo-2-5": {"text": prompt, "voice": "Rachel", "stability": 0.5, "similarityBoost": 0.75, "speed": 1.0, "languageCode": "ru"},
        "elevenlabs-text-to-dialogue-v3": {"dialogue": [{"text": prompt, "voice": "Rachel"}], "stability": 0.5, "languageCode": "ru"},
        "elevenlabs-sound-effect-v2": {"text": prompt, "durationSeconds": 5, "promptInfluence": 0.5},
        "kling-v1-avatar-pro": {"imageUrl": image_url, "audioUrl": prompt, "prompt": "Natural head movement and lip sync"},
        "kling-v1-avatar-standard": {"imageUrl": image_url, "audioUrl": prompt, "prompt": "Talking head animation"},
        "infinitalk-from-audio": {"imageUrl": image_url, "audioUrl": prompt, "prompt": "Natural head movement and lip sync"},
        "wan-2-2-animate-move": {"videoUrl": image_url, "imageUrl": prompt, "duration": 5, "resolution": "720p"},
        "wan-2-2-animate-replace": {"videoUrl": image_url, "imageUrl": prompt, "duration": 5, "resolution": "720p"},
    }
    return payloads.get(model, None)

# ------------------- Обработчики -------------------
# (все обработчики из предыдущего кода, включая start, cancel, clear_dialog, show_balance,
# send_topup_invoice, handle_main_menu, handle_model_selection и т.д.)
# Для экономии места здесь не повторяю, но они должны быть вставлены.

# ------------------- Вебхук и запуск -------------------
async def webhook_handler(request):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return web.Response(text="OK")

async def main_async():
    global app
    init_db()
    if not TELEGRAM_TOKEN or not MASHA_API_KEY:
        logger.error("Не заданы TELEGRAM_TOKEN или MASHA_API_KEY")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Добавьте все обработчики (как в предыдущем коде)...
    # Здесь должен быть полный ConversationHandler и другие хендлеры.
    # Для краткости пропущено, но в вашем коде они есть.

    await app.initialize()
    await app.start()

    webhook_url = "https://nsk7.bothost.ru/api/bots/update"
    await app.bot.set_webhook(webhook_url)
    logger.info(f"Вебхук установлен на {webhook_url}")

    # Создаём aiohttp сервер на порту 8080 (обычно bothost.ru проксирует на 8080)
    aiohttp_app = web.Application()
    aiohttp_app.router.add_post('/api/bots/update', webhook_handler)
    runner = web.AppRunner(aiohttp_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("Сервер запущен на порту 8080")

    while True:
        await asyncio.sleep(3600)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
