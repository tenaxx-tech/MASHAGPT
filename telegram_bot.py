import asyncio
import io
import json
import logging
from typing import List, Tuple
from aiohttp import web

import aiohttp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
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

# ------------------- Цены моделей (в промтах) -------------------
MODEL_PRICES = {
    # Текст
    "gpt-5-nano": 0,
    "gpt-5-mini": 0,
    "gpt-4o-mini": 0,
    "gpt-4.1-nano": 0,
    "deepseek-chat": 0,
    "deepseek-reasoner": 0,
    "grok-4-1-fast-reasoning": 0,
    "grok-4-1-fast-non-reasoning": 0,
    "grok-3-mini": 0,
    "gemini-2.0-flash": 0,
    "gemini-2.0-flash-lite": 0,
    "gemini-2.5-flash-lite": 0,
    "gpt-5.4": 15,
    "gpt-5.1": 10,
    "gpt-5": 10,
    "gpt-4.1": 8,
    "gpt-4o": 10,
    "o3-mini": 4.4,
    "o3": 40,
    "o1": 60,
    "claude-haiku-4-5": 5,
    "claude-sonnet-4-5": 15,
    "claude-opus-4-5": 25,
    "gemini-3-flash": 3,
    "gemini-2.5-pro": 10,
    "gemini-3-pro": 16,
    "gemini-3-pro-image": 12,
    # Изображения – сделаем все бесплатными для теста, но с лимитом 5 в неделю
    "z-image": 0,
    "grok-imagine-text-to-image": 0,
    "codeplugtech-face-swap": 0,
    "cdlingram-face-swap": 0,
    "recraft-crisp-upscale": 0,
    "recraft-remove-background": 0,
    "topaz-image-upscale": 0,
    "flux-2": 0,
    "qwen-edit-multiangle": 0,
    "nano-banana-2": 0,
    "nano-banana-pro": 0,
    "midjourney": 0,
    "gpt-image-1-5-text-to-image": 0,
    "gpt-image-1-5-image-to-image": 0,
    "ideogram-v3-reframe": 0,
    # Видео – оставим платными
    "grok-imagine-text-to-video": 1,
    "wan-2-6-text-to-video": 3,
    "wan-2-5-text-to-video": 3,
    "wan-2-6-image-to-video": 3,
    "wan-2-6-video-to-video": 3,
    "wan-2-5-image-to-video": 3,
    "sora-2-text-to-video": 3,
    "sora-2-image-to-video": 3,
    "veo-3-1": 5,
    "kling-2-6-text-to-video": 6,
    "kling-v2-5-turbo-pro": 6,
    "kling-2-6-image-to-video": 6,
    "kling-v2-5-turbo-image-to-video-pro": 5,
    "sora-2-pro-text-to-video": 5,
    "sora-2-pro-image-to-video": 5,
    "sora-2-pro-storyboard": 7,
    "hailuo-2-3": 4,
    "minimax-video-01-director": 4,
    "seedance-v1-pro-fast": 30,
    "kling-2-6-motion-control": 6,
    # Аудио – бесплатные
    "elevenlabs-tts-multilingual-v2": 0,
    "elevenlabs-tts-turbo-2-5": 0,
    "elevenlabs-text-to-dialogue-v3": 0,
    "elevenlabs-sound-effect-v2": 5,
    # Аватар и анимация – платные
    "kling-v1-avatar-pro": 16,
    "kling-v1-avatar-standard": 8,
    "infinitalk-from-audio": 1.1,
    "wan-2-2-animate-move": 0.75,
    "wan-2-2-animate-replace": 0.75,
}

# ------------------- Клавиатуры -------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Генерация текста")],
        [KeyboardButton("🖼 Генерация изображения")],
        [KeyboardButton("🎬 Генерация видео")],
        [KeyboardButton("✨ Обработка изображений")],
        [KeyboardButton("🎵 Аудио (озвучка, эффекты)")],
        [KeyboardButton("🤖 Аватар / анимация")],
        [KeyboardButton("🧹 Сбросить диалог")],
        [KeyboardButton("💰 Мой баланс")],
        [KeyboardButton("⭐ Пополнить промты")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_text_models_keyboard():
    models = [
        ("gpt-4o-mini", "GPT-4o mini", 0),
        ("gpt-5-mini", "GPT-5 mini", 0),
        ("gpt-5-nano", "GPT-5 nano", 0),
        ("gpt-4.1-nano", "GPT-4.1 nano", 0),
        ("deepseek-chat", "DeepSeek Chat", 0),
        ("deepseek-reasoner", "DeepSeek Reasoner", 0),
        ("grok-4-1-fast-reasoning", "Grok 4.1 Fast (reasoning)", 0),
        ("grok-4-1-fast-non-reasoning", "Grok 4.1 Fast", 0),
        ("grok-3-mini", "Grok 3 mini", 0),
        ("gemini-2.0-flash", "Gemini 2.0 Flash", 0),
        ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite", 0),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", 0),
        ("gpt-5.4", "GPT-5.4", 15),
        ("gpt-5.1", "GPT-5.1", 10),
        ("gpt-5", "GPT-5", 10),
        ("gpt-4.1", "GPT-4.1", 8),
        ("gpt-4o", "GPT-4o", 10),
        ("o3-mini", "O3-mini", 4.4),
        ("o3", "O3", 40),
        ("o1", "O1", 60),
        ("claude-haiku-4-5", "Claude Haiku 4.5", 5),
        ("claude-sonnet-4-5", "Claude Sonnet 4.5", 15),
        ("claude-opus-4-5", "Claude Opus 4.5", 25),
        ("gemini-3-flash", "Gemini 3 Flash", 3),
        ("gemini-2.5-pro", "Gemini 2.5 Pro", 10),
        ("gemini-3-pro", "Gemini 3 Pro", 16),
        ("gemini-3-pro-image", "Gemini 3 Pro Image", 12),
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        if price == 0:
            btn_text = f"{label} (бесплатно)"
        else:
            btn_text = f"{label} ({price} промтов)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_image_models_keyboard():
    models = [
        ("z-image", "Z-Image", 0),
        ("grok-imagine-text-to-image", "Grok Imagine", 0),
        ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
        ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
        ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
        ("recraft-remove-background", "Recraft Remove Background", 0),
        ("topaz-image-upscale", "Topaz Image Upscale", 0),
        ("flux-2", "Flux 2", 0),
        ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0),
        ("nano-banana-2", "Nano Banana 2", 0),
        ("nano-banana-pro", "Nano Banana Pro", 0),
        ("midjourney", "Midjourney", 0),
        ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0),
        ("gpt-image-1-5-image-to-image", "GPT Image 1.5 (img2img)", 0),
        ("ideogram-v3-reframe", "Ideogram V3 Reframe", 0),
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        btn_text = f"{label} (бесплатно)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_video_models_keyboard():
    models = [
        ("grok-imagine-text-to-video", "Grok Imagine Video", 1),
        ("wan-2-6-text-to-video", "Wan 2.6 (txt2vid)", 3),
        ("wan-2-5-text-to-video", "Wan 2.5 (txt2vid)", 3),
        ("wan-2-6-image-to-video", "Wan 2.6 (img2vid)", 3),
        ("wan-2-6-video-to-video", "Wan 2.6 (vid2vid)", 3),
        ("wan-2-5-image-to-video", "Wan 2.5 (img2vid)", 3),
        ("sora-2-text-to-video", "Sora 2 (txt2vid)", 3),
        ("sora-2-image-to-video", "Sora 2 (img2vid)", 3),
        ("veo-3-1", "Google Veo 3.1", 5),
        ("kling-2-6-text-to-video", "Kling 2.6 (txt2vid)", 6),
        ("kling-v2-5-turbo-pro", "Kling V2.5 Turbo Pro", 6),
        ("kling-2-6-image-to-video", "Kling 2.6 (img2vid)", 6),
        ("kling-v2-5-turbo-image-to-video-pro", "Kling V2.5 Turbo I2V Pro", 5),
        ("sora-2-pro-text-to-video", "Sora 2 Pro (txt2vid)", 5),
        ("sora-2-pro-image-to-video", "Sora 2 Pro (img2vid)", 5),
        ("sora-2-pro-storyboard", "Sora 2 Pro Storyboard", 7),
        ("hailuo-2-3", "Hailuo 2.3", 4),
        ("minimax-video-01-director", "Minimax Video-01 Director", 4),
        ("seedance-v1-pro-fast", "Seedance V1 Pro Fast", 30),
        ("kling-2-6-motion-control", "Kling 2.6 Motion Control", 6),
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        btn_text = f"{label} ({price} промтов)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_edit_models_keyboard():
    models = [
        ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
        ("recraft-remove-background", "Recraft Remove Background", 0),
        ("topaz-image-upscale", "Topaz Image Upscale", 0),
        ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
        ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
        ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0),
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        btn_text = f"{label} (бесплатно)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_audio_models_keyboard():
    models = [
        ("elevenlabs-tts-multilingual-v2", "Озвучка (Multilingual)", 0),
        ("elevenlabs-tts-turbo-2-5", "Быстрая озвучка (Turbo)", 0),
        ("elevenlabs-text-to-dialogue-v3", "Диалоги (Dialogue V3)", 0),
        ("elevenlabs-sound-effect-v2", "Звуковые эффекты (Sound Effect V2)", 5),
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        if price == 0:
            btn_text = f"{label} (бесплатно)"
        else:
            btn_text = f"{label} ({price} промтов)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_avatar_models_keyboard():
    models = [
        ("kling-v1-avatar-standard", "Kling Avatar Standard", 8),
        ("kling-v1-avatar-pro", "Kling Avatar Pro", 16),
        ("infinitalk-from-audio", "Infinitalk (говорящая голова)", 1.1),
        ("wan-2-2-animate-move", "Wan Animate Move", 0.75),
        ("wan-2-2-animate-replace", "Wan Animate Replace", 0.75),
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        btn_text = f"{label} ({price} промтов)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔙 Главное меню")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ------------------- Вспомогательные функции -------------------
async def send_long_message(update: Update, text: str):
    if not text:
        logger.warning("Пустой текст для отправки")
        return
    logger.info(f"Отправка длинного сообщения, длина={len(text)}")
    for i in range(0, len(text), 4096):
        part = text[i:i+4096]
        await update.message.reply_text(part)
    logger.info("Все части отправлены")

async def create_task(model: str, payload: dict, retries=3):
    url = f"{MASHA_BASE_URL}/tasks/{model}"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 429:
                        wait = 2 ** attempt
                        logger.warning(f"429 Too Many Requests, повтор через {wait} сек")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("id")
        except Exception as e:
            logger.error(f"Ошибка создания задачи {model} (попытка {attempt+1}): {e}")
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
                resp.raise_for_status()
                return await resp.json()
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
            logger.error(f"Таймаут задачи {task_id}")
            return None

# ------------------- Masha API вызовы -------------------
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
        "max_completion_tokens": 1024,   # уменьшено, чтобы избежать пустого ответа
        "temperature": 1.0
    }

    logger.info(f"Отправка запроса к MashaGPT: модель={model}, длина промпта={len(prompt)}")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            logger.info(f"Получен ответ от MashaGPT, статус={resp.status}")
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"Masha API error {resp.status}: {error_text}")
                raise Exception(f"Masha error: {resp.status}")
            data = await resp.json()
            logger.info(f"Полный JSON ответ: {json.dumps(data, ensure_ascii=False)[:500]}")
            content = None
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0].get("message", {})
                content = message.get("content")
            if not content:
                content = data.get("result") or data.get("output")
            if not content:
                logger.warning("Не удалось извлечь content из ответа")
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
    payloads = {
        # Изображения
        "nano-banana-2": {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"},
        "nano-banana-pro": {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"},
        "z-image": {"prompt": prompt, "aspectRatio": "1:1"},
        "grok-imagine-text-to-image": {"prompt": prompt, "aspectRatio": "1:1"},
        "flux-2": {"prompt": prompt, "model": "pro", "aspectRatio": "1:1", "resolution": "1K"},
        "midjourney": {"taskType": "mj_txt2img", "prompt": prompt, "aspectRatio": "1:1", "speed": "fast"},
        "gpt-image-1-5-text-to-image": {"prompt": prompt, "aspectRatio": "1:1", "quality": "medium"},
        "gpt-image-1-5-image-to-image": {"prompt": prompt, "inputUrls": [image_url]} if image_url else None,
        "ideogram-v3-reframe": {"imageUrl": image_url, "imageSize": "square", "renderingSpeed": "BALANCED"} if image_url else None,
        "recraft-crisp-upscale": {"imageUrl": image_url} if image_url else None,
        "recraft-remove-background": {"imageUrl": image_url} if image_url else None,
        "topaz-image-upscale": {"imageUrl": image_url, "upscaleFactor": "2"} if image_url else None,
        "codeplugtech-face-swap": {"inputImage": image_url.split()[0] if image_url and " " in image_url else None,
                                   "swapImage": image_url.split()[1] if image_url and " " in image_url else None},
        "cdlingram-face-swap": {"inputImage": image_url.split()[0] if image_url and " " in image_url else None,
                                "swapImage": image_url.split()[1] if image_url and " " in image_url else None},
        "qwen-edit-multiangle": {"prompt": prompt, "image": image_url},
        # Видео
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
        # Аудио
        "elevenlabs-tts-multilingual-v2": {"text": prompt, "voice": "Rachel", "stability": 0.5, "similarityBoost": 0.75, "speed": 1.0, "languageCode": "ru"},
        "elevenlabs-tts-turbo-2-5": {"text": prompt, "voice": "Rachel", "stability": 0.5, "similarityBoost": 0.75, "speed": 1.0, "languageCode": "ru"},
        "elevenlabs-text-to-dialogue-v3": {"dialogue": [{"text": prompt, "voice": "Rachel"}], "stability": 0.5, "languageCode": "ru"},
        "elevenlabs-sound-effect-v2": {"text": prompt, "durationSeconds": 5, "promptInfluence": 0.5},
        # Аватар и анимация
        "kling-v1-avatar-pro": {"imageUrl": image_url, "audioUrl": prompt, "prompt": "Natural head movement and lip sync"},
        "kling-v1-avatar-standard": {"imageUrl": image_url, "audioUrl": prompt, "prompt": "Talking head animation"},
        "infinitalk-from-audio": {"imageUrl": image_url, "audioUrl": prompt, "prompt": "Natural head movement and lip sync"},
        "wan-2-2-animate-move": {"videoUrl": image_url, "imageUrl": prompt, "duration": 5, "resolution": "720p"},
        "wan-2-2-animate-replace": {"videoUrl": image_url, "imageUrl": prompt, "duration": 5, "resolution": "720p"},
    }
    return payloads.get(model, None)

# ------------------- Обработчики -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "🤖 *Привет! Я бот с поддержкой ИИ (MashaGPT).*\n\n"
        "Я умею:\n"
        "✏️ генерировать текст (много моделей, бесплатные)\n"
        "🖼 создавать изображения (бесплатные – 5 в неделю)\n"
        "🎬 генерировать видео (платно, цена зависит от модели)\n"
        "✨ обрабатывать изображения (бесплатно)\n"
        "🎵 озвучивать текст, создавать диалоги и звуковые эффекты (бесплатно)\n"
        "🤖 создавать аватары и анимацию (платно)\n\n"
        "*Я помню контекст диалога!* Просто отправляйте сообщения, и я буду отвечать, учитывая историю.\n"
        "Чтобы сменить режим или сбросить историю, используйте кнопки внизу.\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔙 Возвращаемся в главное меню.",
        reply_markup=get_main_keyboard()
    )
    return MAIN_MENU

async def clear_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    clear_history(user_id)
    await update.message.reply_text(
        "🧹 История диалога очищена. Начинаем с чистого листа.",
        reply_markup=get_main_keyboard()
    )
    return MAIN_MENU

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_user_balance(user_id)
    img_used = get_weekly_image_count(user_id)
    await update.message.reply_text(
        f"💰 Ваш баланс (для платных услуг): {bal} промтов\n"
        f"🖼 Бесплатные изображения: {img_used}/5 использовано на этой неделе",
        reply_markup=get_main_keyboard()
    )

async def buy_promts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⭐ Пополнение промтов временно недоступно. Свяжитесь с администратором.",
        reply_markup=get_main_keyboard()
    )

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✏️ Генерация текста":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите модель текста:",
            reply_markup=get_text_models_keyboard()
        )
        return TEXT_GEN
    elif text == "🖼 Генерация изображения":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите модель изображения (бесплатно, 5 в неделю):",
            reply_markup=get_image_models_keyboard()
        )
        return IMAGE_GEN
    elif text == "🎬 Генерация видео":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите модель видео (платно):",
            reply_markup=get_video_models_keyboard()
        )
        return VIDEO_GEN
    elif text == "✨ Обработка изображений":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите модель обработки (бесплатно):",
            reply_markup=get_edit_models_keyboard()
        )
        return EDIT_GEN
    elif text == "🎵 Аудио (озвучка, эффекты)":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите модель аудио (бесплатно):",
            reply_markup=get_audio_models_keyboard()
        )
        return AUDIO_GEN
    elif text == "🤖 Аватар / анимация":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите модель аватара или анимации (платно):",
            reply_markup=get_avatar_models_keyboard()
        )
        return AVATAR_GEN
    elif text == "🧹 Сбросить диалог":
        return await clear_dialog(update, context)
    elif text == "💰 Мой баланс":
        await show_balance(update, context)
        return MAIN_MENU
    elif text == "⭐ Пополнить промты":
        await buy_promts(update, context)
        return MAIN_MENU
    elif text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return MAIN_MENU
    else:
        return await start_dialog(update, context, text)

async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    models = []
    if category == "text":
        models = [
            ("gpt-4o-mini", "GPT-4o mini", 0),
            ("gpt-5-mini", "GPT-5 mini", 0),
            ("gpt-5-nano", "GPT-5 nano", 0),
            ("gpt-4.1-nano", "GPT-4.1 nano", 0),
            ("deepseek-chat", "DeepSeek Chat", 0),
            ("deepseek-reasoner", "DeepSeek Reasoner", 0),
            ("grok-4-1-fast-reasoning", "Grok 4.1 Fast (reasoning)", 0),
            ("grok-4-1-fast-non-reasoning", "Grok 4.1 Fast", 0),
            ("grok-3-mini", "Grok 3 mini", 0),
            ("gemini-2.0-flash", "Gemini 2.0 Flash", 0),
            ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite", 0),
            ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", 0),
            ("gpt-5.4", "GPT-5.4", 15),
            ("gpt-5.1", "GPT-5.1", 10),
            ("gpt-5", "GPT-5", 10),
            ("gpt-4.1", "GPT-4.1", 8),
            ("gpt-4o", "GPT-4o", 10),
            ("o3-mini", "O3-mini", 4.4),
            ("o3", "O3", 40),
            ("o1", "O1", 60),
            ("claude-haiku-4-5", "Claude Haiku 4.5", 5),
            ("claude-sonnet-4-5", "Claude Sonnet 4.5", 15),
            ("claude-opus-4-5", "Claude Opus 4.5", 25),
            ("gemini-3-flash", "Gemini 3 Flash", 3),
            ("gemini-2.5-pro", "Gemini 2.5 Pro", 10),
            ("gemini-3-pro", "Gemini 3 Pro", 16),
            ("gemini-3-pro-image", "Gemini 3 Pro Image", 12),
        ]
    elif category == "image":
        models = [
            ("z-image", "Z-Image", 0),
            ("grok-imagine-text-to-image", "Grok Imagine", 0),
            ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
            ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
            ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
            ("recraft-remove-background", "Recraft Remove Background", 0),
            ("topaz-image-upscale", "Topaz Image Upscale", 0),
            ("flux-2", "Flux 2", 0),
            ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0),
            ("nano-banana-2", "Nano Banana 2", 0),
            ("nano-banana-pro", "Nano Banana Pro", 0),
            ("midjourney", "Midjourney", 0),
            ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0),
            ("gpt-image-1-5-image-to-image", "GPT Image 1.5 (img2img)", 0),
            ("ideogram-v3-reframe", "Ideogram V3 Reframe", 0),
        ]
    elif category == "video":
        models = [
            ("grok-imagine-text-to-video", "Grok Imagine Video", 1),
            ("wan-2-6-text-to-video", "Wan 2.6 (txt2vid)", 3),
            ("wan-2-5-text-to-video", "Wan 2.5 (txt2vid)", 3),
            ("wan-2-6-image-to-video", "Wan 2.6 (img2vid)", 3),
            ("wan-2-6-video-to-video", "Wan 2.6 (vid2vid)", 3),
            ("wan-2-5-image-to-video", "Wan 2.5 (img2vid)", 3),
            ("sora-2-text-to-video", "Sora 2 (txt2vid)", 3),
            ("sora-2-image-to-video", "Sora 2 (img2vid)", 3),
            ("veo-3-1", "Google Veo 3.1", 5),
            ("kling-2-6-text-to-video", "Kling 2.6 (txt2vid)", 6),
            ("kling-v2-5-turbo-pro", "Kling V2.5 Turbo Pro", 6),
            ("kling-2-6-image-to-video", "Kling 2.6 (img2vid)", 6),
            ("kling-v2-5-turbo-image-to-video-pro", "Kling V2.5 Turbo I2V Pro", 5),
            ("sora-2-pro-text-to-video", "Sora 2 Pro (txt2vid)", 5),
            ("sora-2-pro-image-to-video", "Sora 2 Pro (img2vid)", 5),
            ("sora-2-pro-storyboard", "Sora 2 Pro Storyboard", 7),
            ("hailuo-2-3", "Hailuo 2.3", 4),
            ("minimax-video-01-director", "Minimax Video-01 Director", 4),
            ("seedance-v1-pro-fast", "Seedance V1 Pro Fast", 30),
            ("kling-2-6-motion-control", "Kling 2.6 Motion Control", 6),
        ]
    elif category == "edit":
        models = [
            ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
            ("recraft-remove-background", "Recraft Remove Background", 0),
            ("topaz-image-upscale", "Topaz Image Upscale", 0),
            ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
            ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
            ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0),
        ]
    elif category == "audio":
        models = [
            ("elevenlabs-tts-multilingual-v2", "Озвучка (Multilingual)", 0),
            ("elevenlabs-tts-turbo-2-5", "Быстрая озвучка (Turbo)", 0),
            ("elevenlabs-text-to-dialogue-v3", "Диалоги (Dialogue V3)", 0),
            ("elevenlabs-sound-effect-v2", "Звуковые эффекты (Sound Effect V2)", 5),
        ]
    elif category == "avatar":
        models = [
            ("kling-v1-avatar-standard", "Kling Avatar Standard", 8),
            ("kling-v1-avatar-pro", "Kling Avatar Pro", 16),
            ("infinitalk-from-audio", "Infinitalk (говорящая голова)", 1.1),
            ("wan-2-2-animate-move", "Wan Animate Move", 0.75),
            ("wan-2-2-animate-replace", "Wan Animate Replace", 0.75),
        ]
    else:
        await update.message.reply_text("Ошибка категории.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    for model_id, label, price in models:
        if price == 0:
            btn_text = f"{label} (бесплатно)"
        else:
            btn_text = f"{label} ({price} промтов)"
        if text == btn_text:
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = category

            if model_id in ["codeplugtech-face-swap", "cdlingram-face-swap", "qwen-edit-multiangle",
                            "kling-v1-avatar-pro", "kling-v1-avatar-standard", "infinitalk-from-audio",
                            "wan-2-2-animate-move", "wan-2-2-animate-replace"]:
                await update.message.reply_text(
                    f"Извините, модель {label} требует пошагового ввода данных (фото, аудио) – эта функция временно в разработке.",
                    reply_markup=get_main_keyboard()
                )
                return MAIN_MENU

            if category == "text":
                await update.message.reply_text(
                    f"Выбрана модель: {label}\n\nВведите запрос:",
                    reply_markup=get_cancel_keyboard()
                )
                return DIALOG
            else:
                context.user_data['media_category'] = category
                await update.message.reply_text(
                    f"Выбрана модель: {label}\n\nВведите запрос:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_PROMPT

    await update.message.reply_text("Пожалуйста, выберите модель из списка.")
    return MAIN_MENU

async def handle_text_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "text")

async def handle_image_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "image")

async def handle_video_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "video")

async def handle_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "edit")

async def handle_audio_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "audio")

async def handle_avatar_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "avatar")

async def start_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str = None) -> int:
    user_id = update.effective_user.id
    if user_message is None:
        user_message = update.message.text

    if user_message == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'gpt-4o-mini')  # по умолчанию gpt-4o-mini
    price = MODEL_PRICES.get(model, 0)

    save_message(user_id, "user", user_message)
    history = get_history(user_id, limit=10)

    if price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(
                f"❌ Недостаточно промтов. Нужно: {price}, у вас: {get_user_balance(user_id)}. Пополните баланс.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания промтов.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    try:
        await update.message.reply_chat_action("typing")
        answer = await masha_text_generate(user_message, history, model)
        logger.info(f"Ответ от MashaGPT получен, длина={len(answer) if answer else 0}")
        if answer:
            await send_long_message(update, answer)
            logger.info("Ответ отправлен пользователю")
            save_message(user_id, "assistant", answer)
        else:
            logger.warning("Пустой ответ от MashaGPT")
            await update.message.reply_text(
                "❌ Пустой ответ от сервера. Попробуйте позже.",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.exception("Ошибка генерации текста")
        await update.message.reply_text(
            "❌ Произошла ошибка при генерации. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
        if price > 0:
            add_balance(user_id, price)
    return DIALOG

async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    model = context.user_data.get('selected_model')
    price = context.user_data.get('model_price', 0)
    category = context.user_data.get('media_category')
    text = update.message.text

    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not category:
        await update.message.reply_text("Ошибка: не выбрана категория.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not model:
        await update.message.reply_text("Сначала выберите модель в меню.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    payload = build_payload(model, prompt=text)
    if not payload:
        await update.message.reply_text(f"❌ Не удалось сформировать запрос для модели {model}.")
        return MAIN_MENU

    logger.info(f"Генерация {category} с моделью {model}, payload={payload}")

    # Проверка баланса (только для платных)
    if price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(
                f"❌ Недостаточно промтов. Нужно: {price}, у вас: {get_user_balance(user_id)}. Пополните баланс.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания промтов.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    # Лимит бесплатных изображений (цена 0)
    if category == "image" and price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            await update.message.reply_text(
                "❌ Вы уже использовали все 5 бесплатных генераций изображений на этой неделе. Лимит обновится в понедельник.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU

    try:
        await update.message.reply_chat_action("upload_photo" if category != "audio" else "record_audio")
        result_bytes = await masha_media_generate(model, payload)
        if result_bytes:
            if category == "video":
                await update.message.reply_video(video=io.BytesIO(result_bytes), caption=f"🎬 Результат")
            elif category == "audio":
                await update.message.reply_audio(audio=io.BytesIO(result_bytes), title="Аудио", caption="🎵 Готово!")
            else:
                await update.message.reply_photo(photo=io.BytesIO(result_bytes), caption="🖼 Результат")
            if category == "image" and price == 0:
                increment_weekly_image_count(user_id)
            save_message(user_id, "user", f"{category} запрос: {text}")
            save_message(user_id, "assistant", "Контент сгенерирован")
        else:
            await update.message.reply_text("❌ Не удалось получить результат от сервера.")
    except Exception as e:
        logger.exception(f"Ошибка генерации в категории {category}")
        await update.message.reply_text(f"❌ Ошибка: {e}")
        if price > 0:
            add_balance(user_id, price)
    finally:
        await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Health check и запуск -------------------
async def health_check(request):
    return web.Response(text="OK")

async def start_http_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("HTTP health‑check сервер запущен на порту 8080")
    while True:
        await asyncio.sleep(3600)

async def main_async():
    # Запускаем HTTP-сервер для health check (чтобы бота не убивали)
    asyncio.create_task(start_http_server())

    # Инициализация бота
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return
    if not MASHA_API_KEY:
        logger.error("MASHA_API_KEY не задан")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            TEXT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_selection)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_selection)],
            VIDEO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_video_selection)],
            EDIT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_selection)],
            AUDIO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_audio_selection)],
            AVATAR_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_selection)],
            DIALOG: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_dialog)],
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text("Используйте меню.")))

    logger.info("Бот запущен (все модели MashaGPT)")
    # Запускаем polling (без вебхука, так как health check уже есть)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # Держим бота активным
    while True:
        await asyncio.sleep(1)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
