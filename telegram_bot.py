import asyncio
import io
import json
import logging
import os
from typing import List, Tuple
from aiohttp import web

import aiohttp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, PreCheckoutQueryHandler,
    CallbackQueryHandler
)
from telegram.constants import ChatAction

from config import TELEGRAM_TOKEN, MASHA_API_KEY, MASHA_BASE_URL
from database import (
    init_db, save_message, get_history, clear_history, update_user_activity,
    get_user_balance, add_balance, deduct_balance,
    get_weekly_image_count, increment_weekly_image_count
)

# Robokassa
from robokassa import get_payment_url, check_result_signature, check_success_signature
from database import create_robokassa_order, update_robokassa_order_status, get_robokassa_order

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

from PIL import Image

# ------------------- Константы -------------------
PAID_IMAGE_PRICE = 2
ADMIN_IDS = [466829859]   # Ваш Telegram user_id

# ------------------- Состояния -------------------
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, EDIT_GEN, AUDIO_GEN, AVATAR_GEN, DIALOG, AWAIT_PROMPT = range(9)
AWAIT_FACE_SWAP_TARGET = 9
AWAIT_FACE_SWAP_SOURCE = 10
AWAIT_IMAGE_FOR_EDIT = 11
AWAIT_PROMPT_FOR_EDIT = 12
AWAIT_IMAGE_FOR_AVATAR = 13
AWAIT_AUDIO_FOR_AVATAR = 14
AWAIT_VIDEO_FOR_ANIMATE = 15
AWAIT_IMAGE_FOR_ANIMATE = 16
AWAIT_IMAGE_ONLY = 17

POPULAR_MENU = 18
AWAIT_PROMPT_FOR_IMAGE = 19
AWAIT_PHOTO_FOR_ANIMATE = 20
AWAIT_MODE_FOR_ANIMATE = 21
AWAIT_PROMPT_FOR_ANIMATE = 22
AWAIT_PROMPT_FOR_DEEPSEEK = 23

# New states for VK packaging
VK_PACKAGE_NAME = 24
VK_PACKAGE_THEME = 25
VK_PACKAGE_SERVICES = 26
VK_PACKAGE_COLORS = 27
VK_PACKAGE_MENU = 28

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
    "z-image": 0, "grok-imagine-text-to-image": 0,
    "flux-2": 0, "nano-banana-2": 0, "nano-banana-pro": 0,
    "midjourney": 0, "gpt-image-1-5-text-to-image": 0, "gpt-image-1-5-image-to-image": 0,
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
    "grok-imagine-image-to-video": 0,
}

MODEL_INPUT_TYPE = {
    "codeplugtech-face-swap": ("image", "image"),
    "cdlingram-face-swap": ("image", "image"),
    "gpt-image-1-5-image-to-image": ("image", "text"),
    "qwen-edit-multiangle": ("image", "text"),
    "kling-v1-avatar-pro": ("image", "audio"),
    "kling-v1-avatar-standard": ("image", "audio"),
    "infinitalk-from-audio": ("image", "audio"),
    "wan-2-2-animate-move": ("video", "image"),
    "wan-2-2-animate-replace": ("video", "image"),
    "recraft-remove-background": ("image",),
    "recraft-crisp-upscale": ("image",),
    "topaz-image-upscale": ("image",),
    "ideogram-v3-reframe": ("image",),
    "grok-imagine-image-to-video": ("image", "text"),
}

# ------------------- Клавиатуры -------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Генерация текста")],
        [KeyboardButton("🖼 Генерация изображения")],
        [KeyboardButton("🎬 Генерация видео")],
        [KeyboardButton("⭐ Популярные модели генерации")],
        [KeyboardButton("📦 Упаковка группы ВК")],  # new button
        [KeyboardButton("🎵 Аудио (озвучка, эффекты)")],
        [KeyboardButton("🤖 Аватар / анимация")],
        [KeyboardButton("🧹 Сбросить диалог")],
        [KeyboardButton("💰 Мой баланс")],
        [KeyboardButton("⭐ Пополнить промты")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_popular_menu_keyboard():
    keyboard = [
        [KeyboardButton("📝 1. Генерация промтов для изображений")],
        [KeyboardButton("🎥 2. Генерация промтов для видео")],
        [KeyboardButton("🖼️ 3. Оживить фото")],
        [KeyboardButton("🎨 4. Текст в изображение")],
        [KeyboardButton("🧹 5. Удалить фон")],
        [KeyboardButton("✨ 6. Улучшить качество")],
        [KeyboardButton("🔄 7. Заменить лицо")],
        [KeyboardButton("🎨 8. Редактировать изображение (img2img)")],
        [KeyboardButton("🔙 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_text_models_keyboard():
    models = [
        ("gpt-4o-mini", "GPT-4o mini", 0), ("gpt-5-mini", "GPT-5 mini", 0),
        ("gpt-5-nano", "GPT-5 nano", 0), ("gpt-4.1-nano", "GPT-4.1 nano", 0),
        ("deepseek-chat", "DeepSeek Chat", 0), ("deepseek-reasoner", "DeepSeek Reasoner", 0),
        ("grok-4-1-fast-reasoning", "Grok 4.1 Fast (reasoning)", 0),
        ("grok-4-1-fast-non-reasoning", "Grok 4.1 Fast", 0), ("grok-3-mini", "Grok 3 mini", 0),
        ("gemini-2.0-flash", "Gemini 2.0 Flash", 0), ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite", 0),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", 0),
        ("gpt-5.4", "GPT-5.4", 15), ("gpt-5.1", "GPT-5.1", 10), ("gpt-5", "GPT-5", 10),
        ("gpt-4.1", "GPT-4.1", 8), ("gpt-4o", "GPT-4o", 10), ("o3-mini", "O3-mini", 4.4),
        ("o3", "O3", 40), ("o1", "O1", 60), ("claude-haiku-4-5", "Claude Haiku 4.5", 5),
        ("claude-sonnet-4-5", "Claude Sonnet 4.5", 15), ("claude-opus-4-5", "Claude Opus 4.5", 25),
        ("gemini-3-flash", "Gemini 3 Flash", 3), ("gemini-2.5-pro", "Gemini 2.5 Pro", 10),
        ("gemini-3-pro", "Gemini 3 Pro", 16), ("gemini-3-pro-image", "Gemini 3 Pro Image", 12)
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_image_models_keyboard():
    models = [
        ("z-image", "Z-Image", 0), ("grok-imagine-text-to-image", "Grok Imagine", 0),
        ("flux-2", "Flux 2", 0), ("nano-banana-2", "Nano Banana 2", 0),
        ("nano-banana-pro", "Nano Banana Pro", 0), ("midjourney", "Midjourney", 0),
        ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0)
    ]
    keyboard = []
    for model_id, label, price in models:
        keyboard.append([KeyboardButton(f"{label} (бесплатно)")])
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
        ("kling-2-6-motion-control", "Kling 2.6 Motion Control", 6)
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        keyboard.append([KeyboardButton(f"{label} ({price} промтов)")])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_audio_models_keyboard():
    models = [
        ("elevenlabs-tts-multilingual-v2", "Озвучка (Multilingual)", 0),
        ("elevenlabs-tts-turbo-2-5", "Быстрая озвучка (Turbo)", 0),
        ("elevenlabs-text-to-dialogue-v3", "Диалоги (Dialogue V3)", 0),
        ("elevenlabs-sound-effect-v2", "Звуковые эффекты (Sound Effect V2)", 5)
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        if price == 0:
            keyboard.append([KeyboardButton(f"{label} (бесплатно)")])
        else:
            keyboard.append([KeyboardButton(f"{label} ({price} промтов)")])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_avatar_models_keyboard():
    models = [
        ("kling-v1-avatar-standard", "Kling Avatar Standard", 8),
        ("kling-v1-avatar-pro", "Kling Avatar Pro", 16),
        ("infinitalk-from-audio", "Infinitalk (говорящая голова)", 1.1),
        ("wan-2-2-animate-move", "Wan Animate Move", 0.75),
        ("wan-2-2-animate-replace", "Wan Animate Replace", 0.75)
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        keyboard.append([KeyboardButton(f"{label} ({price} промтов)")])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔙 Главное меню")]],
        resize_keyboard=True, one_time_keyboard=True
    )

def get_vk_package_keyboard():
    keyboard = [
        [KeyboardButton("🖥 Обложка ПК (1920×768)")],
        [KeyboardButton("📱 Мобильная обложка (1080×1920)")],
        [KeyboardButton("🔘 Кнопки меню (376×256)")],
        [KeyboardButton("📊 Виджеты (480×720) ×3")],
        [KeyboardButton("👤 Аватарка (1080×1080)")],
        [KeyboardButton("🛍 Товары (карточки)")],
        [KeyboardButton("📁 Обложка подборки")],
        [KeyboardButton("🔙 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# ------------------- Вспомогательные функции -------------------
async def compress_image(image_bytes: bytes, max_size: int = 1280, quality: int = 85) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb = Image.new('RGB', img.size, (255, 255, 255))
            rgb.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb
        ratio = max_size / max(img.size)
        if ratio < 1:
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()

async def send_long_message(update: Update, text: str):
    if not text:
        return
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i+4096])

async def send_action_loop(update: Update, action: ChatAction, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await update.message.reply_chat_action(action)
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break

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
                    if resp.status >= 400:
                        error_body = await resp.text()
                        logger.error(f"create_task error {resp.status}: {error_body}")
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
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"Статус {resp.status}, тело: {text[:200]}")
                    return text
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"Ответ не JSON: {text[:200]}")
                    return text
    except Exception as e:
        logger.error(f"Ошибка получения статуса {task_id}: {e}")
        return None

async def wait_for_task(task_id: str, timeout=300):
    start = asyncio.get_running_loop().time()
    while True:
        data = await get_task_status(task_id)
        if not data:
            await asyncio.sleep(3)
            if asyncio.get_running_loop().time() - start > timeout:
                raise Exception("Таймаут: нет ответа от API")
            continue
        if isinstance(data, str):
            if "429" in data or "500" in data:
                await asyncio.sleep(5)
                continue
            raise Exception(f"Ошибка API: {data[:200]}")
        status = data.get("status")
        if status == "COMPLETED":
            return data
        elif status == "FAILED":
            raise Exception(f"Задача провалилась: {data.get('errorMessage')}")
        await asyncio.sleep(2)
        if asyncio.get_running_loop().time() - start > timeout:
            raise Exception(f"Таймаут {timeout} секунд")

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

async def masha_media_generate(model: str, payload: dict):
    task_id = await create_task(model, payload)
    if not task_id:
        raise Exception("Не удалось создать задачу")
    result = await wait_for_task(task_id)
    if not result:
        raise Exception("Не удалось получить результат")
    if not isinstance(result, dict):
        raise Exception(f"Неверный формат ответа: {result}")
    outputs = result.get("output", [])
    if not outputs:
        raise Exception("Нет output в ответе")
    if isinstance(outputs[0], dict):
        media_url = outputs[0].get("url")
    elif isinstance(outputs[0], str):
        media_url = outputs[0]
    else:
        raise Exception(f"Неизвестный тип output: {type(outputs[0])}")
    if not media_url:
        raise Exception("Нет URL в ответе")
    async with aiohttp.ClientSession() as session:
        async with session.get(media_url) as resp:
            if resp.status != 200:
                raise Exception(f"Ошибка скачивания файла: {resp.status}")
            file_bytes = await resp.read()
    return file_bytes, media_url

def build_payload(model: str, prompt: str = None, image_url: str = None) -> dict:
    if model in ("codeplugtech-face-swap", "cdlingram-face-swap"):
        if image_url and " " in image_url:
            urls = image_url.split()
            return {"inputImage": urls[0], "swapImage": urls[1]}
        return None
    if model == "qwen-edit-multiangle":
        if not prompt or not image_url:
            return None
        return {"prompt": prompt, "image": image_url}
    if model == "grok-imagine-image-to-video":
        payload = {"imageUrl": image_url, "mode": "normal"}
        if prompt:
            payload["prompt"] = prompt
        return payload
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "🤖 *Привет! Я бот с поддержкой ИИ Дмитрия Урецкого.*\n\n"
        "✏️ Текст – бесплатно, без лимита\n"
        "🖼 Изображения – бесплатно, 5 в неделю\n"
        "🎬 Видео, 🎵 Аудио, ✨ Обработка – платно (токены)\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def clear_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    clear_history(update.effective_user.id)
    await update.message.reply_text("История очищена.", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_user_balance(user_id)
    img_used = get_weekly_image_count(user_id)
    img_left = max(0, 5 - img_used)
    
    text = (
        f"👤 **Ваш ID:** `{user_id}`\n"
        f"💰 **Баланс:** {bal} промтов\n"
        f"🖼 **Бесплатные изображения:** {img_used}/5 использовано на этой неделе (осталось {img_left})\n"
        f"💎 **Платное изображение** (после лимита): {PAID_IMAGE_PRICE} промтов\n\n"
        f"📞 **По вопросам:** [Написать создателю](https://t.me/Dmitriy_Uretskiy)"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Пополнить промты (Stars)", callback_data="topup")],
        [InlineKeyboardButton("💳 Пополнить через Робокассу", callback_data="robokassa_topup")],
        [InlineKeyboardButton("📞 Поддержка", url="https://t.me/Dmitriy_Uretskiy")]
    ])
    
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    try:
        target_user_id = int(context.args[0])
        amount = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Использование: /add_balance <user_id> <количество_промтов>\nПример: /add_balance 466829859 100")
        return
    add_balance(target_user_id, amount)
    new_balance = get_user_balance(target_user_id)
    await update.message.reply_text(
        f"✅ Пользователю `{target_user_id}` начислено {amount} промтов.\n"
        f"💰 Новый баланс: {new_balance} промтов.",
        parse_mode="Markdown"
    )

async def send_topup_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    if chat_id is None:
        chat_id = update.effective_chat.id
    title = "Пополнение баланса"
    description = "100 звёзд = 100 промтов"
    payload = "topup_100"
    currency = "XTR"
    prices = [LabeledPrice(label="100 звёзд", amount=100)]

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency=currency,
        prices=prices,
        start_parameter="topup",
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False
    )

# ------------------- Обработчик главного меню -------------------
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✏️ Генерация текста":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель текста:", reply_markup=get_text_models_keyboard())
        return TEXT_GEN
    elif text == "🖼 Генерация изображения":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель изображения:", reply_markup=get_image_models_keyboard())
        return IMAGE_GEN
    elif text == "🎬 Генерация видео":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель видео:", reply_markup=get_video_models_keyboard())
        return VIDEO_GEN
    elif text == "⭐ Популярные модели генерации":
        context.user_data.clear()
        await update.message.reply_text(
            "Выберите нужную функцию:",
            reply_markup=get_popular_menu_keyboard()
        )
        return POPULAR_MENU
    elif text == "📦 Упаковка группы ВК":
        context.user_data.clear()
        await update.message.reply_text(
            "📦 Давайте создадим стильную упаковку для вашей группы ВКонтакте.\n\n"
            "Введите **название группы**:",
            reply_markup=get_cancel_keyboard()
        )
        return VK_PACKAGE_NAME
    elif text == "🎵 Аудио (озвучка, эффекты)":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель аудио:", reply_markup=get_audio_models_keyboard())
        return AUDIO_GEN
    elif text == "🤖 Аватар / анимация":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель аватара:", reply_markup=get_avatar_models_keyboard())
        return AVATAR_GEN
    elif text == "🧹 Сбросить диалог":
        return await clear_dialog(update, context)
    elif text == "💰 Мой баланс":
        await show_balance(update, context)
        return MAIN_MENU
    elif text == "⭐ Пополнить промты":
        await send_topup_invoice(update, context)
        return MAIN_MENU
    elif text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    else:
        return await start_dialog(update, context, text)

# ------------------- Обработчик выбора модели (универсальный) -------------------
async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Проверяем текстовые модели
    text_models = [
        ("gpt-4o-mini", "GPT-4o mini", 0), ("gpt-5-mini", "GPT-5 mini", 0),
        ("gpt-5-nano", "GPT-5 nano", 0), ("gpt-4.1-nano", "GPT-4.1 nano", 0),
        ("deepseek-chat", "DeepSeek Chat", 0), ("deepseek-reasoner", "DeepSeek Reasoner", 0),
        ("grok-4-1-fast-reasoning", "Grok 4.1 Fast (reasoning)", 0),
        ("grok-4-1-fast-non-reasoning", "Grok 4.1 Fast", 0), ("grok-3-mini", "Grok 3 mini", 0),
        ("gemini-2.0-flash", "Gemini 2.0 Flash", 0), ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite", 0),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", 0),
        ("gpt-5.4", "GPT-5.4", 15), ("gpt-5.1", "GPT-5.1", 10), ("gpt-5", "GPT-5", 10),
        ("gpt-4.1", "GPT-4.1", 8), ("gpt-4o", "GPT-4o", 10), ("o3-mini", "O3-mini", 4.4),
        ("o3", "O3", 40), ("o1", "O1", 60), ("claude-haiku-4-5", "Claude Haiku 4.5", 5),
        ("claude-sonnet-4-5", "Claude Sonnet 4.5", 15), ("claude-opus-4-5", "Claude Opus 4.5", 25),
        ("gemini-3-flash", "Gemini 3 Flash", 3), ("gemini-2.5-pro", "Gemini 2.5 Pro", 10),
        ("gemini-3-pro", "Gemini 3 Pro", 16), ("gemini-3-pro-image", "Gemini 3 Pro Image", 12)
    ]
    for model_id, label, price in text_models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = 'text'
            context.user_data['media_category'] = 'text'
            await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите ваш запрос:", reply_markup=get_cancel_keyboard())
            return DIALOG

    # Проверяем модели изображений (чистые text-to-image)
    image_models = [
        ("z-image", "Z-Image", 0), ("grok-imagine-text-to-image", "Grok Imagine", 0),
        ("flux-2", "Flux 2", 0), ("nano-banana-2", "Nano Banana 2", 0),
        ("nano-banana-pro", "Nano Banana Pro", 0), ("midjourney", "Midjourney", 0),
        ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0)
    ]
    for model_id, label, price in image_models:
        btn_text = f"{label} (бесплатно)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = 'image'
            context.user_data['media_category'] = 'image'
            await update.message.reply_text(
                f"Выбрана модель: {label}\n\nВведите текстовое описание:",
                reply_markup=get_cancel_keyboard()
            )
            return AWAIT_PROMPT

    # Проверяем модели видео
    video_models = [
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
        ("kling-2-6-motion-control", "Kling 2.6 Motion Control", 6)
    ]
    for model_id, label, price in video_models:
        btn_text = f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = 'video'
            context.user_data['media_category'] = 'video'
            input_type = MODEL_INPUT_TYPE.get(model_id, ("text",))
            if input_type == ("video", "image"):
                await update.message.reply_text(
                    "🔹 Анимация персонажа\n\n"
                    "1️⃣ Отправьте **видео-референс** (движение)\n"
                    "2️⃣ Затем отправьте **изображение персонажа**\n\n"
                    "Отправьте первое видео:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_VIDEO_FOR_ANIMATE
            elif input_type == ("image", "text"):
                await update.message.reply_text(
                    "🔹 Image-to-Video\n\n"
                    "1️⃣ Отправьте **изображение**\n"
                    "2️⃣ Затем отправьте **текстовое описание** движения\n\n"
                    "Отправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_FOR_EDIT
            else:
                await update.message.reply_text(
                    f"Выбрана модель: {label}\n\nВведите текстовое описание видео:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_PROMPT

    # Проверяем аудио модели
    audio_models = [
        ("elevenlabs-tts-multilingual-v2", "Озвучка (Multilingual)", 0),
        ("elevenlabs-tts-turbo-2-5", "Быстрая озвучка (Turbo)", 0),
        ("elevenlabs-text-to-dialogue-v3", "Диалоги (Dialogue V3)", 0),
        ("elevenlabs-sound-effect-v2", "Звуковые эффекты (Sound Effect V2)", 5)
    ]
    for model_id, label, price in audio_models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = 'audio'
            context.user_data['media_category'] = 'audio'
            await update.message.reply_text(
                f"Выбрана модель: {label}\n\nВведите текст (или описание звука):",
                reply_markup=get_cancel_keyboard()
            )
            return AWAIT_PROMPT

    # Проверяем модели аватара
    avatar_models = [
        ("kling-v1-avatar-standard", "Kling Avatar Standard", 8),
        ("kling-v1-avatar-pro", "Kling Avatar Pro", 16),
        ("infinitalk-from-audio", "Infinitalk (говорящая голова)", 1.1),
        ("wan-2-2-animate-move", "Wan Animate Move", 0.75),
        ("wan-2-2-animate-replace", "Wan Animate Replace", 0.75)
    ]
    for model_id, label, price in avatar_models:
        btn_text = f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = 'avatar'
            context.user_data['media_category'] = 'avatar'
            input_type = MODEL_INPUT_TYPE.get(model_id, ("image", "audio"))
            if input_type == ("image", "audio"):
                await update.message.reply_text(
                    "🔹 Говорящий аватар\n\n"
                    "1️⃣ Отправьте **фото лица**\n"
                    "2️⃣ Затем отправьте **аудиофайл** (MP3/WAV)\n\n"
                    "Отправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_FOR_AVATAR
            elif input_type == ("video", "image"):
                await update.message.reply_text(
                    "🔹 Анимация персонажа\n\n"
                    "1️⃣ Отправьте **видео-референс** (движение)\n"
                    "2️⃣ Затем отправьте **изображение персонажа**\n\n"
                    "Отправьте первое видео:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_VIDEO_FOR_ANIMATE
            else:
                await update.message.reply_text(
                    f"Выбрана модель: {label}\n\nВведите описание:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_PROMPT

    await update.message.reply_text("Пожалуйста, выберите модель из списка или вернитесь в главное меню.", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Обработчик диалога (текст) -------------------
async def start_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str = None) -> int:
    user_id = update.effective_user.id
    if user_message is None:
        user_message = update.message.text
    if user_message == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'gpt-4o-mini')
    price = MODEL_PRICES.get(model, 0)

    save_message(user_id, "user", user_message)
    history = get_history(user_id, limit=10)

    if price > 0 and get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}, у вас: {get_user_balance(user_id)}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if price > 0 and not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.TYPING, stop_action))
    try:
        answer = await masha_text_generate(user_message, history, model)
    except Exception as e:
        logger.exception("Ошибка генерации текста")
        if price > 0:
            add_balance(user_id, price)
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return DIALOG
    finally:
        stop_action.set()
        await action_task

    if answer:
        await send_long_message(update, answer)
        save_message(user_id, "assistant", answer)
    else:
        await update.message.reply_text("❌ Пустой ответ от сервера.")
        if price > 0:
            add_balance(user_id, price)
    return DIALOG

# ------------------- Обработчик для одношаговой генерации (промпт) -------------------
async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    model = context.user_data.get('selected_model')
    price = context.user_data.get('model_price', 0)
    category = context.user_data.get('media_category')
    prompt = update.message.text

    if prompt == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not prompt or prompt.isspace():
        await update.message.reply_text("Пожалуйста, введите текст запроса.", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT

    payload = build_payload(model, prompt=prompt)
    if not payload:
        await update.message.reply_text(f"❌ Не удалось сформировать запрос для модели {model}.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    used = 0
    paid = False
    if category == "image" and price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            balance = get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
                paid = True
            else:
                await update.message.reply_text(f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.", reply_markup=get_main_keyboard())
                return MAIN_MENU
    elif price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        paid = False
    else:
        paid = False

    action = ChatAction.UPLOAD_PHOTO if category == "image" else ChatAction.TYPING
    if category == "video":
        action = ChatAction.UPLOAD_VIDEO
    elif category == "audio":
        action = ChatAction.RECORD_AUDIO

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, action, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка генерации медиа")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if (category == "image" and price == 0 and used >= 5) or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        if category == "video":
            await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🎬 Результат")
        elif category == "audio":
            await update.message.reply_audio(audio=io.BytesIO(result_bytes), title="Аудио", caption="🎵 Готово!")
        else:
            compressed = await compress_image(result_bytes)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат (сжатое)")
            await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
            if category == "image" and price == 0 and used < 5:
                increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"{category} запрос: {prompt}")
        save_message(user_id, "assistant", "Контент сгенерирован")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if (category == "image" and price == 0 and used >= 5) or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Обработчики для популярного меню -------------------
async def handle_popular_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    elif text == "📝 1. Генерация промтов для изображений":
        context.user_data['pending_action'] = 'prompt_image'
        await update.message.reply_text(
            "Введите описание того, что вы хотите изобразить, а я сгенерирую подробный промт для нейросети.\n"
            "Например: «корабль в космосе» или «портрет девушки в стиле киберпанк»",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_PROMPT_FOR_DEEPSEEK

    elif text == "🎥 2. Генерация промтов для видео":
        context.user_data['pending_action'] = 'prompt_video'
        await update.message.reply_text(
            "Опишите сюжет видео, а я создам промт для генерации видео.\n"
            "Например: «человек бежит по пустыне на закате, камера сзади»",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_PROMPT_FOR_DEEPSEEK

    elif text == "🖼️ 3. Оживить фото":
        context.user_data['pending_action'] = 'animate_photo'
        await update.message.reply_text(
            "🔹 **Оживление фото** (модель Wan 2.6, платно: 3 промта)\n\n"
            "Отправьте **фото**, которое хотите оживить (JPEG/PNG).\n"
            "Затем вы сможете добавить текстовое описание движения (необязательно).",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_PHOTO_FOR_ANIMATE

    elif text == "🎨 4. Текст в изображение":
        context.user_data['selected_model'] = 'nano-banana-2'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text(
            "Введите текстовое описание изображения, которое хотите сгенерировать.\n"
            "Пример: «кот в скафандре на Марсе»",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_PROMPT_FOR_IMAGE

    elif text == "🧹 5. Удалить фон":
        context.user_data['selected_model'] = 'recraft-remove-background'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text(
            "Отправьте **изображение**, с которого нужно удалить фон.",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_IMAGE_ONLY

    elif text == "✨ 6. Улучшить качество":
        context.user_data['selected_model'] = 'recraft-crisp-upscale'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text(
            "Отправьте **изображение**, которое нужно улучшить (увеличить разрешение до 4x).",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_IMAGE_ONLY

    elif text == "🔄 7. Заменить лицо":
        keyboard = [
            [KeyboardButton("CodePlugTech (быстрый, бесплатно)")],
            [KeyboardButton("CDIngram (качественный, бесплатно)")],
            [KeyboardButton("🔙 Назад")]
        ]
        await update.message.reply_text(
            "Выберите модель для замены лица:\n"
            "• CodePlugTech – быстрый и доступный\n"
            "• CDIngram – улучшенная детализация\n\n"
            "Обе модели бесплатны (лимит 5 изображений в неделю).",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        context.user_data['pending_action'] = 'face_swap'
        return POPULAR_MENU

    elif text == "🎨 8. Редактировать изображение (img2img)":
        context.user_data['selected_model'] = 'gpt-image-1-5-image-to-image'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text(
            "🔹 Редактирование изображения по описанию (img2img)\n\n"
            "1️⃣ Отправьте **изображение**, которое хотите изменить\n"
            "2️⃣ Затем отправьте **текстовое описание** изменений (на русском, поддерживается кириллица)\n\n"
            "Отправьте первое фото:",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_IMAGE_FOR_EDIT

    elif text in ("CodePlugTech (быстрый, бесплатно)", "CDIngram (качественный, бесплатно)"):
        model_id = "codeplugtech-face-swap" if "CodePlugTech" in text else "cdlingram-face-swap"
        context.user_data['selected_model'] = model_id
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text(
            "🔹 Замена лица\n\n"
            "1️⃣ Отправьте **целевое изображение** (куда вставить лицо)\n"
            "2️⃣ Затем отправьте **изображение-источник лица**\n\n"
            "Отправьте первое фото:",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_FACE_SWAP_TARGET

    else:
        await update.message.reply_text("Пожалуйста, выберите пункт из меню.", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU

# ------------------- Обработчики для пунктов популярного меню -------------------
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import json
import asyncio
import logging

logger = logging.getLogger(__name__)

async def handle_deepseek_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_input = update.message.text
    if user_input == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    action = context.user_data.get('pending_action')
    
    if action == 'prompt_image':
        system_prompt = (
            "Ты — эксперт по промтам для генерации изображений. Создай два промта в формате JSON (classic и hightech) по запросу пользователя.\n"
            "Правила:\n"
            "- Используй русский язык. В полях 'content' внутри 'text_on_image' текст должен быть ЗАГЛАВНЫМИ БУКВАМИ (крупная кириллица).\n"
            "- В остальных полях (scene, person, background_action, mood_and_lighting) пиши обычным регистром, коротко, но визуально ёмко.\n"
            "- Добавь поле 'brief_description' для каждого стиля. Это краткое описание сцены на русском, 10–20 слов, обычный регистр (не капс).\n"
            "- Обязательно укажи движение, свет, цветовую гамму, атмосферу.\n"
            "- Лицо героя — как на загруженном фото (не изменять черты).\n"
            "- Формат: 16:9, фотореализм, высокое разрешение.\n"
            "Структура JSON:\n"
            "{\n"
            "  \"classic\": {\n"
            "    \"brief_description\": \"Краткое описание классической сцены\",\n"
            "    \"scene\": \"...\",\n"
            "    \"atmosphere\": \"...\",\n"
            "    \"person\": {\n"
            "      \"description\": \"...\",\n"
            "      \"preservation\": \"лицо максимально реалистичное, черты сохранены\"\n"
            "    },\n"
            "    \"background_action\": { ... },\n"
            "    \"text_on_image\": [\n"
            "      {\"position\": \"верхняя треть, слева\", \"content\": \"СЕГОДНЯ\", \"style\": \"крупный полупрозрачный фон, строгий шрифт\"},\n"
            "      {\"position\": \"верхняя треть, справа\", \"content\": \"20:00\", \"style\": \"крупный ярко-оранжевый, жирный\"},\n"
            "      {\"position\": \"нижняя треть, по центру\", \"content\": \"УСПЕТЬ В ПОСЛЕДНИЙ ВАГОН\", \"style\": \"очень крупный белый или жёлтый, жирный, с подложкой\"}\n"
            "    ],\n"
            "    \"mood_and_lighting\": \"...\"\n"
            "  },\n"
            "  \"hightech\": {\n"
            "    \"brief_description\": \"Краткое описание хай-тек сцены\",\n"
            "    \"scene\": \"... (киберпанк, прозрачный поезд, неон)\",\n"
            "    ... (аналогичная структура, но с футуристическими элементами)\n"
            "  }\n"
            "}\n"
            "В поле 'background_action' можно описать фон и второстепенные объекты.\n"
            "Текст на изображении (text_on_image) должен быть обязательно, хотя бы одна фраза.\n"
            "Выведи только JSON-объект, без пояснений. Ключи classic и hightech обязательны.\n"
        )
        user_prompt = f"{system_prompt}\n\nЗАПРОС ПОЛЬЗОВАТЕЛЯ: «{user_input}»\n\nТОЛЬКО JSON:"
    elif action == 'prompt_video':
        system_prompt = (
            "Ты — эксперт по видеопромтам. Создай два JSON-промта (classic и hightech) для генерации видео по запросу пользователя.\n"
            "Правила:\n"
            "- Русский язык. В полях 'text_overlay' текст — ЗАГЛАВНЫМИ БУКВАМИ.\n"
            "- Добавь поле 'brief_description' для каждого стиля: краткое описание видео на русском, 10–20 слов, обычный регистр.\n"
            "- Опиши движение камеры, тайминг (0–1.5с, 1.5–3.5с, 3.5–5с), свет, цветовую палитру, формат (16:9), длительность 5 сек, 24fps.\n"
            "- В хай-тек стиле добавь неон, глюки, цифровые элементы.\n"
            "Структура JSON:\n"
            "{\n"
            "  \"classic\": {\n"
            "    \"brief_description\": \"...\",\n"
            "    \"description\": \"...\",\n"
            "    \"camera\": \"...\",\n"
            "    \"lighting_palette\": \"...\",\n"
            "    \"timeline\": [\n"
            "      {\"time\": \"0-1.5s\", \"action\": \"...\"},\n"
            "      {\"time\": \"1.5-3.5s\", \"action\": \"...\"},\n"
            "      {\"time\": \"3.5-5s\", \"action\": \"...\"}\n"
            "    ],\n"
            "    \"text_overlay\": [\n"
            "      {\"time\": \"0.5s\", \"content\": \"СЕГОДНЯ\", \"position\": \"верхний левый угол\"},\n"
            "      ...\n"
            "    ],\n"
            "    \"format\": \"16:9, 5s, 24fps\"\n"
            "  },\n"
            "  \"hightech\": { ... аналог }\n"
            "}\n"
            "Только JSON, без лишнего текста."
        )
        user_prompt = f"{system_prompt}\n\nЗАПРОС ПОЛЬЗОВАТЕЛЯ: «{user_input}»\n\nТОЛЬКО JSON:"
    else:
        await update.message.reply_text("Ошибка: действие не определено.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    save_message(user_id, "user", user_input)
    history = get_history(user_id, limit=5)

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.TYPING, stop_action))
    try:
        answer = await masha_text_generate(user_prompt, history, "deepseek-chat")
        if not answer:
            raise ValueError("Пустой ответ от модели")
        answer = answer.strip()
        if answer.startswith("```json"):
            answer = answer[7:]
        if answer.startswith("```"):
            answer = answer[3:]
        if answer.endswith("```"):
            answer = answer[:-3]
        answer = answer.strip()
        data = json.loads(answer)
        classic = data.get("classic", {})
        hightech = data.get("hightech", {})
        classic_prompt = json.dumps(classic, ensure_ascii=False, indent=2)
        hightech_prompt = json.dumps(hightech, ensure_ascii=False, indent=2)
        classic_desc = classic.get("brief_description", "")
        hightech_desc = hightech.get("brief_description", "")
    except Exception as e:
        logger.exception("Ошибка генерации промтов")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:300]}")
        return POPULAR_MENU
    finally:
        stop_action.set()
        await action_task

    context.user_data['last_classic_prompt'] = classic_prompt
    context.user_data['last_hightech_prompt'] = hightech_prompt

    if classic_desc:
        await update.message.reply_text(f"📖 *Описание:* {classic_desc}", parse_mode="Markdown")
    await update.message.reply_text(
        f"✨ **Классический стиль (JSON)**\n\n```json\n{classic_prompt}\n```",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Копировать", callback_data="copy_classic")]]),
        parse_mode="Markdown"
    )

    if hightech_desc:
        await update.message.reply_text(f"🚀 *Описание:* {hightech_desc}", parse_mode="Markdown")
    await update.message.reply_text(
        f"💡 **Хай-тек стиль (JSON)**\n\n```json\n{hightech_prompt}\n```",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Копировать", callback_data="copy_hightech")]]),
        parse_mode="Markdown"
    )

    await update.message.reply_text(
        "💡 **Как использовать:**\n"
        "• Нажмите на кнопку под нужным стилем → бот пришлёт JSON в отдельном сообщении, его легко скопировать.\n"
        "• Вставьте JSON в нейросеть (Midjourney, DALL-E, Kling и др.).\n"
        "• Текст на изображении (поля `content`) уже написан ЗАГЛАВНЫМИ, как вы просили.\n"
        "• Описание перед JSON — только для ознакомления, оно не копируется.",
        reply_markup=get_popular_menu_keyboard()
    )
    return POPULAR_MENU

async def copy_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "copy_classic":
        text = context.user_data.get('last_classic_prompt', "")
    elif query.data == "copy_hightech":
        text = context.user_data.get('last_hightech_prompt', "")
    else:
        return
    if text:
        await query.message.reply_text(
            f"✅ Скопируйте JSON:\n\n```json\n{text}\n```",
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text("❌ Нет сохранённого промта. Сгенерируйте заново.")

async def handle_text_to_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    prompt = update.message.text
    if prompt == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'nano-banana-2')
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(
                f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU

    payload = build_payload(model, prompt=prompt)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка генерации изображения")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if not paid:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"text-to-image: {prompt}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- НОВАЯ ВЕРСИЯ ОЖИВЛЕНИЯ ФОТО (Wan 2.6, платно, без выбора режима) -------------------
async def handle_animate_photo_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Приём фото
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте фото (JPEG/PNG).", reply_markup=get_cancel_keyboard())
            return AWAIT_PHOTO_FOR_ANIMATE

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фото.", reply_markup=get_cancel_keyboard())
        return AWAIT_PHOTO_FOR_ANIMATE

    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    context.user_data['animate_photo_url'] = photo_url

    await update.message.reply_text(
        "✅ Фото получено.\n\n"
        "Теперь вы можете отправить **текстовое описание** движения (например, «камера медленно приближается, листья колышутся»).\n"
        "Если не хотите добавлять описание, напишите **пропустить**.",
        reply_markup=get_cancel_keyboard()
    )
    return AWAIT_PROMPT_FOR_ANIMATE

async def handle_animate_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    photo_url = context.user_data.get('animate_photo_url')
    if not photo_url:
        await update.message.reply_text("Ошибка: фото не найдено. Начните заново.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Определяем модель и цену
    model = "wan-2-6-image-to-video"
    price = 3  # промтов

    # Проверка баланса
    balance = get_user_balance(user_id)
    if balance < price:
        await update.message.reply_text(
            f"❌ Недостаточно промтов для оживления фото. Нужно: {price}, у вас: {balance}.\n"
            "Пополните баланс через кнопку «💰 Мой баланс».",
            reply_markup=get_main_keyboard()
        )
        return MAIN_MENU

    # Списание
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания промтов.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Определяем промпт (если пользователь ввёл "пропустить" или пустую строку – None)
    prompt = None
    if text.lower() != "пропустить" and text:
        prompt = text

    # Формируем payload через build_payload
    payload = build_payload(model, prompt=prompt, image_url=photo_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос для Wan 2.6.", reply_markup=get_main_keyboard())
        add_balance(user_id, price)  # возвращаем списанное
        return MAIN_MENU

    # Отправляем действие "Загрузка видео"
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))

    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка оживления фото (Wan 2.6)")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)  # возврат при ошибке
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🖼️ Оживлённое видео (Wan 2.6)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        save_message(user_id, "user", f"animate photo (Wan 2.6): {prompt if prompt else 'без описания'}")
        save_message(user_id, "assistant", "Видео создано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)  # возврат

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ========== Обработчики для однократных изображений (удаление фона, улучшение) ==========
async def handle_single_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение.", reply_markup=get_cancel_keyboard())
            return AWAIT_IMAGE_ONLY

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_ONLY

    photo_file = await update.message.photo[-1].get_file()
    image_url = photo_file.file_path
    model = context.user_data.get('selected_model')
    user_id = update.effective_user.id

    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(
                f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU

    payload = build_payload(model, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос.", reply_markup=get_main_keyboard())
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка обработки изображения")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        caption = "🖼 Результат (сжатое)"
        if model == "recraft-remove-background":
            caption = "🧹 Фон удалён (сжатое)"
        elif model == "recraft-crisp-upscale":
            caption = "✨ Улучшенное качество (сжатое)"
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption=caption)
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if not paid:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"image processing: {model}")
        save_message(user_id, "assistant", "Изображение обработано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Обработчики для face swap, edit, avatar, animate (остались без изменений) -------------------
async def handle_face_swap_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте целевое изображение.", reply_markup=get_cancel_keyboard())
            return AWAIT_FACE_SWAP_TARGET

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте целевое изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_FACE_SWAP_TARGET

    photo_file = await update.message.photo[-1].get_file()
    target_url = photo_file.file_path
    context.user_data['target_image_url'] = target_url
    await update.message.reply_text(
        "✅ Целевое фото получено. Теперь отправьте **изображение-источник лица**:",
        reply_markup=get_cancel_keyboard()
    )
    return AWAIT_FACE_SWAP_SOURCE

async def handle_face_swap_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение-источник лица.", reply_markup=get_cancel_keyboard())
            return AWAIT_FACE_SWAP_SOURCE

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение-источник лица.", reply_markup=get_cancel_keyboard())
        return AWAIT_FACE_SWAP_SOURCE

    photo_file = await update.message.photo[-1].get_file()
    swap_url = photo_file.file_path
    target_url = context.user_data.get('target_image_url')
    if not target_url:
        await update.message.reply_text("Ошибка: не найдено целевое фото. Начните заново.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'codeplugtech-face-swap')
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(
                f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU

    image_url = f"{target_url} {swap_url}"
    payload = build_payload(model, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос для замены лица.", reply_markup=get_main_keyboard())
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка face-swap")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат замены лица (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if not paid:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"face-swap: target={target_url}, swap={swap_url}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def handle_edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text(
                "Пожалуйста, отправьте изображение, которое хотите изменить.",
                reply_markup=get_cancel_keyboard()
            )
            return AWAIT_IMAGE_FOR_EDIT

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_EDIT

    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    context.user_data['edit_image_url'] = photo_url
    await update.message.reply_text(
        "✅ Изображение получено. Теперь отправьте **текстовое описание** изменений (на русском):",
        reply_markup=get_cancel_keyboard()
    )
    return AWAIT_PROMPT_FOR_EDIT

async def handle_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt_text = update.message.text
    if prompt_text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    image_url = context.user_data.get('edit_image_url')
    if not image_url:
        await update.message.reply_text("Ошибка: не найдено изображение. Начните заново.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'gpt-image-1-5-image-to-image')
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(
                f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.",
                reply_markup=get_main_keyboard()
            )
            return MAIN_MENU

    payload = build_payload(model, prompt=prompt_text, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос.", reply_markup=get_main_keyboard())
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка редактирования изображения (img2img)")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат редактирования (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if not paid:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"edit image (img2img): {prompt_text}")
        save_message(user_id, "assistant", "Изображение отредактировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def handle_avatar_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте фото лица (чёткое, анфас).", reply_markup=get_cancel_keyboard())
            return AWAIT_IMAGE_FOR_AVATAR

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фото лица.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_AVATAR

    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    context.user_data['avatar_image_url'] = photo_url
    await update.message.reply_text(
        "✅ Фото получено. Теперь отправьте **аудиофайл** (MP3/WAV) с речью:",
        reply_markup=get_cancel_keyboard()
    )
    return AWAIT_AUDIO_FOR_AVATAR

async def handle_avatar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте аудиофайл (MP3/WAV) или голосовое сообщение.", reply_markup=get_cancel_keyboard())
            return AWAIT_AUDIO_FOR_AVATAR

    if not update.message.audio and not update.message.voice:
        await update.message.reply_text("Пожалуйста, отправьте аудиофайл или голосовое сообщение.", reply_markup=get_cancel_keyboard())
        return AWAIT_AUDIO_FOR_AVATAR

    if update.message.audio:
        audio_file = await update.message.audio.get_file()
    else:
        audio_file = await update.message.voice.get_file()
    audio_url = audio_file.file_path
    image_url = context.user_data.get('avatar_image_url')
    if not image_url:
        await update.message.reply_text("Ошибка: не найдено фото. Начните заново.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'kling-v1-avatar-standard')
    price = context.user_data.get('model_price', 8)
    user_id = update.effective_user.id

    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    payload = build_payload(model, prompt=audio_url, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос для аватара.", reply_markup=get_main_keyboard())
        add_balance(user_id, price)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка генерации аватара")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🤖 Аватар готов")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        save_message(user_id, "user", f"avatar: image={image_url}, audio={audio_url}")
        save_message(user_id, "assistant", "Аватар создан")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def handle_animate_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте видео-референс (движение).", reply_markup=get_cancel_keyboard())
            return AWAIT_VIDEO_FOR_ANIMATE

    if not update.message.video:
        await update.message.reply_text("Пожалуйста, отправьте видео-референс.", reply_markup=get_cancel_keyboard())
        return AWAIT_VIDEO_FOR_ANIMATE

    video_file = await update.message.video.get_file()
    video_url = video_file.file_path
    context.user_data['animate_video_url'] = video_url
    await update.message.reply_text(
        "✅ Видео получено. Теперь отправьте **изображение персонажа**:",
        reply_markup=get_cancel_keyboard()
    )
    return AWAIT_IMAGE_FOR_ANIMATE

async def handle_animate_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение персонажа.", reply_markup=get_cancel_keyboard())
            return AWAIT_IMAGE_FOR_ANIMATE

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение персонажа.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_ANIMATE

    photo_file = await update.message.photo[-1].get_file()
    image_url = photo_file.file_path
    video_url = context.user_data.get('animate_video_url')
    if not video_url:
        await update.message.reply_text("Ошибка: не найдено видео. Начните заново.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'wan-2-2-animate-move')
    price = context.user_data.get('model_price', 0.75)
    user_id = update.effective_user.id

    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    payload = build_payload(model, prompt=image_url, image_url=video_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос для анимации.", reply_markup=get_main_keyboard())
        add_balance(user_id, price)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка анимации персонажа")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🎬 Анимация готова")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        save_message(user_id, "user", f"animate: video={video_url}, image={image_url}")
        save_message(user_id, "assistant", "Анимация создана")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ========== НОВЫЕ ОБРАБОТЧИКИ ДЛЯ УПАКОВКИ ГРУППЫ ВК ==========
async def vk_package_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_group_name'] = text
    await update.message.reply_text(
        "Укажите **тематику** группы (например: кулинария, IT, фитнес, психология):",
        reply_markup=get_cancel_keyboard()
    )
    return VK_PACKAGE_THEME

async def vk_package_theme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_theme'] = text
    await update.message.reply_text(
        "Перечислите **услуги / товары**, которые предоставляет группа (через запятую):",
        reply_markup=get_cancel_keyboard()
    )
    return VK_PACKAGE_SERVICES

async def vk_package_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_services'] = text
    await update.message.reply_text(
        "Введите **цвета оформления** (например: #FF5733, #FFFFFF, синий, серый):",
        reply_markup=get_cancel_keyboard()
    )
    return VK_PACKAGE_COLORS

async def vk_package_colors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_colors'] = text

    await update.message.reply_text(
        "✅ Параметры сохранены!\n\n"
        "Теперь выберите, какой элемент упаковки сгенерировать:",
        reply_markup=get_vk_package_keyboard()
    )
    return VK_PACKAGE_MENU

async def vk_package_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Получаем сохранённые параметры
    group_name = context.user_data.get('vk_group_name', 'Название группы')
    theme = context.user_data.get('vk_theme', 'тематика')
    services = context.user_data.get('vk_services', 'услуги')
    colors = context.user_data.get('vk_colors', 'цвета')

    # Определяем тип и размеры
    if text == "🖥 Обложка ПК (1920×768)":
        width, height = 1920, 768
        element_type = "обложка для ПК"
        prompt_suffix = "горизонтальный баннер, широкоформатный, для шапки группы ВК"
    elif text == "📱 Мобильная обложка (1080×1920)":
        width, height = 1080, 1920
        element_type = "мобильная обложка"
        prompt_suffix = "вертикальный баннер, для мобильной версии ВК"
    elif text == "🔘 Кнопки меню (376×256)":
        width, height = 376, 256
        element_type = "кнопка меню"
        prompt_suffix = "иконка или кнопка для меню сообщества, минималистичный дизайн"
    elif text == "📊 Виджеты (480×720) ×3":
        return await generate_multiple_widgets(update, context, group_name, theme, services, colors)
    elif text == "👤 Аватарка (1080×1080)":
        width, height = 1080, 1080
        element_type = "аватарка"
        prompt_suffix = "квадратная аватарка сообщества, яркая, запоминающаяся"
    elif text == "🛍 Товары (карточки)":
        width, height = 800, 800
        element_type = "карточки товаров"
        prompt_suffix = "коллаж из карточек товаров, каждая карточка содержит название и цену (условно)"
    elif text == "📁 Обложка подборки":
        width, height = 1200, 800
        element_type = "обложка для подборки товаров"
        prompt_suffix = "обложка для каталога или подборки товаров ВК, привлекательная"
    else:
        await update.message.reply_text("Пожалуйста, выберите пункт из меню.", reply_markup=get_vk_package_keyboard())
        return VK_PACKAGE_MENU

    # Для всех, кроме виджетов, генерируем одно изображение
    prompt = (
        f"Создай {element_type} для группы ВКонтакте.\n"
        f"Название группы: {group_name}\n"
        f"Тематика: {theme}\n"
        f"Услуги/товары: {services}\n"
        f"Цветовая гамма: {colors}\n"
        f"Размер изображения: {width}×{height} пикселей.\n"
        f"Стиль: {prompt_suffix}. Современный, чистый, профессиональный дизайн. "
        f"Текст должен быть хорошо читаемым. Используй указанные цвета."
    )

    return await generate_vk_image(update, context, prompt, width, height, element_type)

async def generate_multiple_widgets(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                     group_name, theme, services, colors):
    """Генерирует три виджета (480×720) последовательно"""
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    # Проверка лимита / списания (как в handle_media_input)
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов за первый виджет.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    for i in range(1, 4):
        prompt = (
            f"Создай виджет {i} из трёх для группы ВКонтакте.\n"
            f"Название группы: {group_name}\n"
            f"Тематика: {theme}\n"
            f"Услуги/товары: {services}\n"
            f"Цветовая гамма: {colors}\n"
            f"Размер: 480×720 пикселей.\n"
            f"Виджет может содержать информацию: акция, услуга, контакт или кнопка. "
            f"Стиль минималистичный, информативный. Все три виджета должны быть в едином стиле."
        )
        result_bytes, media_url = await generate_vk_image_raw(update, context, prompt, 480, 720, f"виджет {i}")
        if result_bytes:
            compressed = await compress_image(result_bytes)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption=f"📊 Виджет {i}")
            await update.message.reply_text(f"📥 Скачать оригинал виджета {i}: {media_url}")
            if not paid and i == 1 and used < 5:
                increment_weekly_image_count(user_id)   # увеличиваем счётчик только один раз за три виджета
        else:
            await update.message.reply_text(f"❌ Не удалось сгенерировать виджет {i}.")

    await update.message.reply_text("Все три виджета сгенерированы! Что дальше?", reply_markup=get_vk_package_keyboard())
    return VK_PACKAGE_MENU

async def generate_vk_image(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, width: int, height: int, element_type: str):
    """Обёртка для генерации одного изображения с проверкой лимита и отправкой"""
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    result_bytes, media_url = await generate_vk_image_raw(update, context, prompt, width, height, element_type)
    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption=f"🖼 {element_type} (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if not paid and used < 5:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"VK package: {element_type}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    else:
        await update.message.reply_text(f"❌ Не удалось получить результат для {element_type}.")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_vk_package_keyboard())
    return VK_PACKAGE_MENU

async def generate_vk_image_raw(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, width: int, height: int, element_type: str):
    """Низкоуровневая генерация через MashaGPT"""
    model = "nano-banana-2"  # можно заменить на flux-2 или midjourney
    # Добавляем размер в параметры payload
    payload = {
        "prompt": prompt,
        "aspectRatio": f"{width}:{height}",
        "resolution": "1K"
    }
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
        return result_bytes, media_url
    except Exception as e:
        logger.exception(f"Ошибка генерации {element_type}")
        await update.message.reply_text(f"❌ Ошибка генерации: {str(e)[:200]}")
        return None, None

# ========== ОБРАБОТЧИКИ ДЛЯ ROBOKASSA (с кнопками выбора суммы) ==========
async def inline_robokassa_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("100 ₽", callback_data="robokassa_100")],
        [InlineKeyboardButton("250 ₽", callback_data="robokassa_250")],
        [InlineKeyboardButton("500 ₽", callback_data="robokassa_500")],
        [InlineKeyboardButton("1000 ₽", callback_data="robokassa_1000")],
    ])
    await query.message.reply_text(
        "💰 Выберите сумму пополнения через Робокассу:",
        reply_markup=keyboard
    )

async def handle_robokassa_amount_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data
    if not data.startswith("robokassa_"):
        return

    try:
        amount = int(data.split("_")[1])
    except (IndexError, ValueError):
        await query.message.reply_text("❌ Неверная сумма.")
        return

    if amount < 100:
        await query.message.reply_text("Минимальная сумма 100 руб.")
        return

    import time
    inv_id = int(time.time() * 100) % 10**9
    create_robokassa_order(inv_id, user_id, amount)

    link = get_payment_url(inv_id, amount, description=f"Пополнение баланса на {amount} промтов")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Перейти к оплате", url=link)]
    ])

    await query.message.reply_text(
        f"Счёт на сумму {amount} руб. создан.\n\n"
        f"Нажмите на кнопку ниже, чтобы оплатить через Robokassa.\n"
        f"После оплаты ваш баланс пополнится автоматически.\n\n"
        f"Номер заказа: `{inv_id}`",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await query.message.reply_text("Вы можете продолжить работу:", reply_markup=get_main_keyboard())

# ------------------- Обработчики платежей (Stars) -------------------
async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload == "topup_100":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Неизвестный товар")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    amount = update.message.successful_payment.total_amount
    add_balance(user_id, amount)
    await update.message.reply_text(
        f"✅ Баланс пополнен на {amount} промтов! Теперь у вас {get_user_balance(user_id)} промтов.",
        reply_markup=get_main_keyboard()
    )

async def inline_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "topup":
        await send_topup_invoice(update, context, chat_id=query.message.chat_id)

# ------------------- Веб-сервер для health и Robokassa -------------------
async def run_web_server_with_robokassa(port, bot_instance):
    web_app = web.Application()
    
    async def health(request):
        return web.Response(text="OK")
    
    async def robokassa_result(request):
        data = await request.post()
        params = dict(data)
        logger.info(f"Robokassa result notification: {params}")
        
        if not check_result_signature(params):
            logger.error("Invalid signature for result notification")
            return web.Response(text="bad sign", status=400)
        
        inv_id = int(params.get("InvId"))
        out_sum = float(params.get("OutSum"))
        order = get_robokassa_order(inv_id)
        
        if not order:
            logger.error(f"Order {inv_id} not found")
            return web.Response(text=f"Order {inv_id} not found", status=404)
        
        if order["status"] == "success":
            return web.Response(text=f"OK{inv_id}")
        
        if abs(order["amount"] - out_sum) > 0.01:
            logger.error(f"Amount mismatch: {order['amount']} vs {out_sum}")
            return web.Response(text="amount mismatch", status=400)
        
        user_id = order["user_id"]
        add_balance(user_id, order["amount"])
        update_robokassa_order_status(inv_id, "success")
        
        try:
            await bot_instance.send_message(
                chat_id=user_id,
                text=f"✅ Ваш баланс пополнен на {order['amount']} промтов через Robokassa!"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
        return web.Response(text=f"OK{inv_id}")
    
    async def robokassa_success(request):
        params = dict(request.query)
        logger.info(f"Robokassa success redirect: {params}")
        if not check_success_signature(params):
            return web.Response(text="bad sign", status=400)
        inv_id = params.get("InvId")
        html = f"""
        <html>
        <head><title>Оплата успешна</title></head>
        <body>
            <h1>Спасибо за оплату!</h1>
            <p>Ваш заказ №{inv_id} оплачен. Баланс пополнен.</p>
            <p>Вы можете вернуться в телеграм-бота и продолжить пользоваться сервисом.</p>
        </body>
        </html>
        """
        return web.Response(text=html, content_type="text/html")
    
    async def robokassa_fail(request):
        params = dict(request.query)
        logger.info(f"Robokassa fail redirect: {params}")
        inv_id = params.get("InvId")
        html = f"""
        <html>
        <head><title>Оплата не удалась</title></head>
        <body>
            <h1>Оплата не была завершена</h1>
            <p>Заказ №{inv_id}. Если вы не оплачивали, попробуйте ещё раз.</p>
            <p>Вернитесь в бота и создайте новый счёт.</p>
        </body>
        </html>
        """
        return web.Response(text=html, content_type="text/html")
    
    web_app.router.add_get('/health', health)
    web_app.router.add_post('/robokassa/result', robokassa_result)
    web_app.router.add_get('/robokassa/success', robokassa_success)
    web_app.router.add_get('/robokassa/fail', robokassa_fail)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server (health + robokassa) запущен на порту {port}")
    await asyncio.Event().wait()

# ------------------- Запуск -------------------
async def main_async():
    init_db()
    if not TELEGRAM_TOKEN or not MASHA_API_KEY:
        logger.error("Не заданы TELEGRAM_TOKEN или MASHA_API_KEY")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu),
                CallbackQueryHandler(inline_robokassa_topup, pattern="robokassa_topup"),
                CallbackQueryHandler(handle_robokassa_amount_choice, pattern="^robokassa_\\d+$"),
            ],
            TEXT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            VIDEO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            EDIT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            AUDIO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            AVATAR_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            DIALOG: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_dialog)],
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media_input)],
            AWAIT_FACE_SWAP_TARGET: [
                MessageHandler(filters.PHOTO, handle_face_swap_target),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_face_swap_target)
            ],
            AWAIT_FACE_SWAP_SOURCE: [
                MessageHandler(filters.PHOTO, handle_face_swap_source),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_face_swap_source)
            ],
            AWAIT_IMAGE_FOR_EDIT: [
                MessageHandler(filters.PHOTO, handle_edit_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_image)
            ],
            AWAIT_PROMPT_FOR_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_prompt)],
            AWAIT_IMAGE_FOR_AVATAR: [
                MessageHandler(filters.PHOTO, handle_avatar_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_image)
            ],
            AWAIT_AUDIO_FOR_AVATAR: [
                MessageHandler(filters.AUDIO | filters.VOICE, handle_avatar_audio),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_audio)
            ],
            AWAIT_VIDEO_FOR_ANIMATE: [
                MessageHandler(filters.VIDEO, handle_animate_video),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_video)
            ],
            AWAIT_IMAGE_FOR_ANIMATE: [
                MessageHandler(filters.PHOTO, handle_animate_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_image)
            ],
            AWAIT_IMAGE_ONLY: [
                MessageHandler(filters.PHOTO, handle_single_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_single_image)
            ],
            POPULAR_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_popular_menu)],
            AWAIT_PROMPT_FOR_DEEPSEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deepseek_prompt)],
            AWAIT_PROMPT_FOR_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_to_image)],
            AWAIT_PHOTO_FOR_ANIMATE: [
                MessageHandler(filters.PHOTO, handle_animate_photo_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_photo)
            ],
            AWAIT_PROMPT_FOR_ANIMATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_prompt)],
            # New VK packaging states
            VK_PACKAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_name)],
            VK_PACKAGE_THEME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_theme)],
            VK_PACKAGE_SERVICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_services)],
            VK_PACKAGE_COLORS: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_colors)],
            VK_PACKAGE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_menu)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(CommandHandler("add_balance", add_balance_command))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(inline_topup_callback, pattern="topup"))
    app.add_handler(CallbackQueryHandler(copy_prompt_callback, pattern="^copy_(classic|hightech)$"))

    port = int(os.getenv("PORT", 8080))
    asyncio.create_task(run_web_server_with_robokassa(port, app.bot))

    logger.info("Запуск бота в режиме polling")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

def main():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
    finally:
        try:
            loop.close()
        except:
            pass

if __name__ == "__main__":
    main()
