import asyncio
import io
import json
import logging
import os
import time
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
from PIL import Image

from config import TELEGRAM_TOKEN, MASHA_API_KEY, MASHA_BASE_URL
from database import (
    init_db, save_message, get_history, clear_history, update_user_activity,
    get_user_balance, add_balance, deduct_balance,
    get_weekly_image_count, increment_weekly_image_count
)
from robokassa import get_payment_url, check_result_signature, check_success_signature
from database import create_robokassa_order, update_robokassa_order_status, get_robokassa_order

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

PAID_IMAGE_PRICE = 2
ADMIN_IDS = [466829859]

# ------------------- Состояния -------------------
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, EDIT_GEN, AUDIO_GEN, AVATAR_GEN, DIALOG, AWAIT_PROMPT = range(9)
AWAIT_FACE_SWAP_TARGET, AWAIT_FACE_SWAP_SOURCE, AWAIT_IMAGE_FOR_EDIT, AWAIT_PROMPT_FOR_EDIT = 9, 10, 11, 12
AWAIT_IMAGE_FOR_AVATAR, AWAIT_AUDIO_FOR_AVATAR, AWAIT_VIDEO_FOR_ANIMATE, AWAIT_IMAGE_FOR_ANIMATE, AWAIT_IMAGE_ONLY = 13, 14, 15, 16, 17
POPULAR_MENU, AWAIT_PROMPT_FOR_IMAGE, AWAIT_PHOTO_FOR_ANIMATE, AWAIT_MODE_FOR_ANIMATE, AWAIT_PROMPT_FOR_ANIMATE = 18, 19, 20, 21, 22
AWAIT_PROMPT_FOR_DEEPSEEK = 23
VK_PACKAGE_NAME, VK_PACKAGE_THEME, VK_PACKAGE_SERVICES, VK_PACKAGE_ADVANTAGES, VK_PACKAGE_COLORS, VK_PACKAGE_MENU = 24, 25, 26, 27, 28, 29

# ------------------- Цены моделей (полный список) -------------------
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
        [KeyboardButton("📦 Упаковка группы ВК")],
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
async def compress_image(image_bytes: bytes, max_size: int = 1920, quality: int = 85) -> bytes:
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
        "gpt-image-1-5-text-to-image": {"prompt": prompt, "quality": "medium"},   # size убран
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
    # ------------------- Обработчики (все, включая старые) -------------------
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
        f"🖼 **Бесплатные изображения:** {img_used}/5 использовано (осталось {img_left})\n"
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
        await update.message.reply_text("⛔ Нет прав.")
        return
    try:
        target = int(context.args[0])
        amount = int(context.args[1])
    except:
        await update.message.reply_text("❌ Использование: /add_balance <user_id> <количество>")
        return
    add_balance(target, amount)
    await update.message.reply_text(f"✅ Пользователю {target} начислено {amount} промтов.")

async def send_topup_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    if chat_id is None:
        chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Пополнение баланса",
        description="100 звёзд = 100 промтов",
        payload="topup_100",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="100 звёзд", amount=100)],
        start_parameter="topup"
    )

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
        await update.message.reply_text("Выберите нужную функцию:", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU
    elif text == "📦 Упаковка группы ВК":
        context.user_data.clear()
        await update.message.reply_text(
            "📦 *Упаковка группы ВКонтакте*\n\n"
            "Я создам стильные обложки, кнопки, виджеты и аватарку для вашего сообщества.\n"
            "Для наилучшего результата мне понадобится несколько параметров.\n\n"
            "Введите **название группы**:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
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

async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Текстовые модели
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

    # Изображения
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
            await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите описание:", reply_markup=get_cancel_keyboard())
            return AWAIT_PROMPT

    # Видео
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
                    "🔹 Анимация персонажа\n\n1️⃣ Отправьте видео-референс\n2️⃣ Затем изображение персонажа\nОтправьте первое видео:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_VIDEO_FOR_ANIMATE
            elif input_type == ("image", "text"):
                await update.message.reply_text(
                    "🔹 Image-to-Video\n\n1️⃣ Отправьте изображение\n2️⃣ Затем текстовое описание\nОтправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_FOR_EDIT
            else:
                await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите описание видео:", reply_markup=get_cancel_keyboard())
                return AWAIT_PROMPT

    # Аудио
    audio_models = [
        ("elevenlabs-tts-multilingual-v2", "Озвучка (Multilingual)", 0),
        ("elevenlabs-tts-turbo-2-5", "Быстрая озвучка (Turbo)", 0),
        ("elevenlabs-text-to-dialogue-v3", "Диалоги (Dialogue V3)", 0),
        ("elevenlabs-sound-effect-v2", "Звуковые эффекты", 5)
    ]
    for model_id, label, price in audio_models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = 'audio'
            context.user_data['media_category'] = 'audio'
            await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите текст или описание звука:", reply_markup=get_cancel_keyboard())
            return AWAIT_PROMPT

    # Аватары
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
                    "🔹 Говорящий аватар\n\n1️⃣ Отправьте фото лица\n2️⃣ Отправьте аудиофайл (MP3/WAV)\nОтправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_FOR_AVATAR
            elif input_type == ("video", "image"):
                await update.message.reply_text(
                    "🔹 Анимация персонажа\n\n1️⃣ Отправьте видео-референс\n2️⃣ Отправьте изображение персонажа\nОтправьте первое видео:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_VIDEO_FOR_ANIMATE
            else:
                await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите описание:", reply_markup=get_cancel_keyboard())
                return AWAIT_PROMPT

    await update.message.reply_text("Пожалуйста, выберите модель из списка.", reply_markup=get_main_keyboard())
    return MAIN_MENU

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
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if price > 0 and not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.TYPING, stop_action))
    try:
        answer = await masha_text_generate(user_message, history, model)
    except Exception as e:
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
        await update.message.reply_text("❌ Пустой ответ.")
        if price > 0:
            add_balance(user_id, price)
    return DIALOG

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
        await update.message.reply_text("Введите текст запроса.", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT

    payload = build_payload(model, prompt=prompt)
    if not payload:
        await update.message.reply_text(f"❌ Не удалось сформировать запрос для {model}.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    used = 0
    paid = False
    if category == "image" and price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            balance = get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
                paid = True
            else:
                await update.message.reply_text(f"❌ Бесплатный лимит исчерпан. Нужно {PAID_IMAGE_PRICE} промтов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
    elif price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    action = ChatAction.UPLOAD_PHOTO if category == "image" else ChatAction.TYPING
    if category == "video": action = ChatAction.UPLOAD_VIDEO
    elif category == "audio": action = ChatAction.RECORD_AUDIO

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
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат")
            await update.message.reply_text(f"📥 Оригинал: {media_url}")
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

# ------------------- Обработчики популярного меню (DeepSeek, тексты) -------------------
async def handle_popular_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    elif text == "📝 1. Генерация промтов для изображений":
        context.user_data['pending_action'] = 'prompt_image'
        await update.message.reply_text("Введите описание для генерации промта изображения:", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_DEEPSEEK
    elif text == "🎥 2. Генерация промтов для видео":
        context.user_data['pending_action'] = 'prompt_video'
        await update.message.reply_text("Введите описание для генерации промта видео:", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_DEEPSEEK
    elif text == "🖼️ 3. Оживить фото":
        context.user_data['pending_action'] = 'animate_photo'
        await update.message.reply_text("Отправьте фото для оживления (Wan 2.6, 3 промта):", reply_markup=get_cancel_keyboard())
        return AWAIT_PHOTO_FOR_ANIMATE
    elif text == "🎨 4. Текст в изображение":
        context.user_data['selected_model'] = 'nano-banana-2'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text("Введите текстовое описание изображения:", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_IMAGE
    elif text == "🧹 5. Удалить фон":
        context.user_data['selected_model'] = 'recraft-remove-background'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text("Отправьте изображение для удаления фона:", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_ONLY
    elif text == "✨ 6. Улучшить качество":
        context.user_data['selected_model'] = 'recraft-crisp-upscale'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text("Отправьте изображение для улучшения качества:", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_ONLY
    elif text == "🔄 7. Заменить лицо":
        keyboard = [
            [KeyboardButton("CodePlugTech (быстрый, бесплатно)")],
            [KeyboardButton("CDIngram (качественный, бесплатно)")],
            [KeyboardButton("🔙 Назад")]
        ]
        await update.message.reply_text("Выберите модель замены лица:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True))
        context.user_data['pending_action'] = 'face_swap'
        return POPULAR_MENU
    elif text == "🎨 8. Редактировать изображение (img2img)":
        context.user_data['selected_model'] = 'gpt-image-1-5-image-to-image'
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text("Отправьте изображение для редактирования:", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_EDIT
    elif text in ("CodePlugTech (быстрый, бесплатно)", "CDIngram (качественный, бесплатно)"):
        model_id = "codeplugtech-face-swap" if "CodePlugTech" in text else "cdlingram-face-swap"
        context.user_data['selected_model'] = model_id
        context.user_data['model_price'] = 0
        context.user_data['media_category'] = 'image'
        await update.message.reply_text("Отправьте целевое изображение (куда вставить лицо):", reply_markup=get_cancel_keyboard())
        return AWAIT_FACE_SWAP_TARGET
    else:
        await update.message.reply_text("Выберите пункт из меню.", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU

async def handle_deepseek_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_input = update.message.text
    if user_input == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    action = context.user_data.get('pending_action')
    if action == 'prompt_image':
        system_prompt = "Ты — эксперт по промтам. Создай JSON (classic и hightech) по запросу. Только JSON."
        user_prompt = f"{system_prompt}\nЗапрос: {user_input}\nJSON:"
    elif action == 'prompt_video':
        system_prompt = "Ты — эксперт по видеопромтам. Создай JSON (classic и hightech) по запросу. Только JSON."
        user_prompt = f"{system_prompt}\nЗапрос: {user_input}\nJSON:"
    else:
        await update.message.reply_text("Ошибка.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    save_message(user_id, "user", user_input)
    history = get_history(user_id, limit=5)
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.TYPING, stop_action))
    try:
        answer = await masha_text_generate(user_prompt, history, "deepseek-chat")
        answer = answer.strip()
        if answer.startswith("```json"): answer = answer[7:]
        if answer.startswith("```"): answer = answer[3:]
        if answer.endswith("```"): answer = answer[:-3]
        data = json.loads(answer)
        classic = data.get("classic", {})
        hightech = data.get("hightech", {})
        classic_prompt = json.dumps(classic, ensure_ascii=False, indent=2)
        hightech_prompt = json.dumps(hightech, ensure_ascii=False, indent=2)
        context.user_data['last_classic_prompt'] = classic_prompt
        context.user_data['last_hightech_prompt'] = hightech_prompt
        await update.message.reply_text(
            f"✨ **Классический стиль**\n```json\n{classic_prompt}\n```",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Копировать", callback_data="copy_classic")]]),
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"💡 **Хай-тек стиль**\n```json\n{hightech_prompt}\n```",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Копировать", callback_data="copy_hightech")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:300]}")
    finally:
        stop_action.set()
        await action_task
    await update.message.reply_text("Выберите действие:", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

async def copy_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "copy_classic":
        text = context.user_data.get('last_classic_prompt', "")
    else:
        text = context.user_data.get('last_hightech_prompt', "")
    if text:
        await query.message.reply_text(f"```json\n{text}\n```", parse_mode="Markdown")
    else:
        await query.message.reply_text("Нет сохранённого промта.")

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
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Не хватает промтов. Нужно {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    payload = build_payload(model, prompt=prompt)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка генерации")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task
    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат")
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        if not paid:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"text-to-image: {prompt}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Оживление фото (Wan 2.6) -------------------
async def handle_animate_photo_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if update.message.text:
        await update.message.reply_text("Отправьте фото.", reply_markup=get_cancel_keyboard())
        return AWAIT_PHOTO_FOR_ANIMATE
    if not update.message.photo:
        await update.message.reply_text("Отправьте фото.", reply_markup=get_cancel_keyboard())
        return AWAIT_PHOTO_FOR_ANIMATE
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['animate_photo_url'] = photo_file.file_path
    await update.message.reply_text("Теперь отправьте текстовое описание движения (или 'пропустить'):", reply_markup=get_cancel_keyboard())
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
        await update.message.reply_text("Ошибка: фото не найдено.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    model = "wan-2-6-image-to-video"
    price = 3
    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    prompt = None if text.lower() == "пропустить" else text
    payload = build_payload(model, prompt=prompt, image_url=photo_url)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
        add_balance(user_id, price)
        return MAIN_MENU
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка оживления")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task
    if result_bytes:
        await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🖼️ Оживлённое видео")
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        save_message(user_id, "user", f"animate photo: {prompt or 'без описания'}")
        save_message(user_id, "assistant", "Видео создано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)
    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Обработчики для однократных изображений -------------------
async def handle_single_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Отправьте изображение.", reply_markup=get_cancel_keyboard())
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
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Не хватает промтов. Нужно {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    payload = build_payload(model, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка обработки")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task
    if result_bytes:
        compressed = await compress_image(result_bytes)
        caption = "Результат"
        if model == "recraft-remove-background": caption = "🧹 Фон удалён"
        elif model == "recraft-crisp-upscale": caption = "✨ Улучшенное качество"
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption=caption)
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        if not paid: increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"image processing: {model}")
        save_message(user_id, "assistant", "Обработано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Face Swap, Edit, Avatar, Animate (пропущенные обработчики) -------------------
async def handle_face_swap_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Отправьте целевое изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_FACE_SWAP_TARGET
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['target_image_url'] = photo_file.file_path
    await update.message.reply_text("Теперь отправьте изображение-источник лица:", reply_markup=get_cancel_keyboard())
    return AWAIT_FACE_SWAP_SOURCE

async def handle_face_swap_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Отправьте изображение-источник лица.", reply_markup=get_cancel_keyboard())
        return AWAIT_FACE_SWAP_SOURCE
    photo_file = await update.message.photo[-1].get_file()
    swap_url = photo_file.file_path
    target_url = context.user_data.get('target_image_url')
    if not target_url:
        await update.message.reply_text("Ошибка: целевое фото не найдено.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    model = context.user_data.get('selected_model', 'codeplugtech-face-swap')
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Не хватает промтов. Нужно {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    image_url = f"{target_url} {swap_url}"
    payload = build_payload(model, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка face-swap")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task
    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат замены лица")
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        if not paid: increment_weekly_image_count(user_id)
        save_message(user_id, "user", "face-swap")
        save_message(user_id, "assistant", "Готово")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def handle_edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Отправьте изображение для редактирования.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_EDIT
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['edit_image_url'] = photo_file.file_path
    await update.message.reply_text("Теперь отправьте текстовое описание изменений:", reply_markup=get_cancel_keyboard())
    return AWAIT_PROMPT_FOR_EDIT

async def handle_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt_text = update.message.text
    if prompt_text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    image_url = context.user_data.get('edit_image_url')
    if not image_url:
        await update.message.reply_text("Ошибка: изображение не найдено.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    model = context.user_data.get('selected_model', 'gpt-image-1-5-image-to-image')
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Не хватает промтов. Нужно {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    payload = build_payload(model, prompt=prompt_text, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка редактирования")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task
    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат редактирования")
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        if not paid: increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"edit image: {prompt_text}")
        save_message(user_id, "assistant", "Изображение отредактировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid: add_balance(user_id, PAID_IMAGE_PRICE)
    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def handle_avatar_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Отправьте фото лица.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_AVATAR
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['avatar_image_url'] = photo_file.file_path
    await update.message.reply_text("Теперь отправьте аудиофайл (MP3/WAV) с речью:", reply_markup=get_cancel_keyboard())
    return AWAIT_AUDIO_FOR_AVATAR

async def handle_avatar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not (update.message.audio or update.message.voice):
        await update.message.reply_text("Отправьте аудиофайл или голосовое сообщение.", reply_markup=get_cancel_keyboard())
        return AWAIT_AUDIO_FOR_AVATAR
    if update.message.audio:
        audio_file = await update.message.audio.get_file()
    else:
        audio_file = await update.message.voice.get_file()
    audio_url = audio_file.file_path
    image_url = context.user_data.get('avatar_image_url')
    if not image_url:
        await update.message.reply_text("Ошибка: фото не найдено.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    model = context.user_data.get('selected_model', 'kling-v1-avatar-standard')
    price = context.user_data.get('model_price', 8)
    user_id = update.effective_user.id
    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    payload = build_payload(model, prompt=audio_url, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
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
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        save_message(user_id, "user", f"avatar: image={image_url}")
        save_message(user_id, "assistant", "Аватар создан")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)
    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def handle_animate_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.video:
        await update.message.reply_text("Отправьте видео-референс.", reply_markup=get_cancel_keyboard())
        return AWAIT_VIDEO_FOR_ANIMATE
    video_file = await update.message.video.get_file()
    context.user_data['animate_video_url'] = video_file.file_path
    await update.message.reply_text("Теперь отправьте изображение персонажа:", reply_markup=get_cancel_keyboard())
    return AWAIT_IMAGE_FOR_ANIMATE

async def handle_animate_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Отправьте изображение персонажа.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_FOR_ANIMATE
    photo_file = await update.message.photo[-1].get_file()
    image_url = photo_file.file_path
    video_url = context.user_data.get('animate_video_url')
    if not video_url:
        await update.message.reply_text("Ошибка: видео не найдено.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    model = context.user_data.get('selected_model', 'wan-2-2-animate-move')
    price = context.user_data.get('model_price', 0.75)
    user_id = update.effective_user.id
    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    payload = build_payload(model, prompt=image_url, image_url=video_url)
    if not payload:
        await update.message.reply_text("❌ Ошибка запроса.", reply_markup=get_main_keyboard())
        add_balance(user_id, price)
        return MAIN_MENU
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка анимации")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task
    if result_bytes:
        await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🎬 Анимация готова")
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        save_message(user_id, "user", f"animate: video={video_url}")
        save_message(user_id, "assistant", "Анимация создана")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)
    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Упаковка ВК (с DeepSeek и GPT Image 2) -------------------
async def vk_package_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_group_name'] = update.message.text
    await update.message.reply_text("Укажите тематику группы:", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_THEME

async def vk_package_theme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_theme'] = update.message.text
    await update.message.reply_text("Перечислите услуги/товары (через запятую):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_SERVICES

async def vk_package_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_services'] = update.message.text
    await update.message.reply_text("Напишите ваши преимущества (через запятую):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_ADVANTAGES

async def vk_package_advantages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_advantages'] = update.message.text
    await update.message.reply_text("Введите цвета оформления (например: #FF5733, синий):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_COLORS

async def vk_package_colors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_colors'] = update.message.text

    group = context.user_data.get('vk_group_name', 'Название')
    theme = context.user_data.get('vk_theme', '')
    services = context.user_data.get('vk_services', '')
    advantages = context.user_data.get('vk_advantages', '')
    colors = context.user_data.get('vk_colors', '')
    await update.message.reply_text("🔄 Генерирую промпт через DeepSeek...", parse_mode="Markdown")
    deepseek_prompt = f"""
Ты дизайнер обложек ВК. На основе данных создай промпт.
Название: {group}, тема: {theme}, услуги/товары: {services}, преимущества: {advantages}, цвета: {colors}.
Требования: левая часть – название и преимущества, правая – товары/услуги с иконками. Верхние 20% пустые. Только русский язык, заглавные буквы. Без коллажей.
Напиши только промпт.
"""
    try:
        generated = await masha_text_generate(deepseek_prompt, [], "deepseek-chat")
        if not generated:
            generated = f"Создай обложку для группы '{group}'. Тема: {theme}. Цвета: {colors}. Текст крупно."
    except:
        generated = f"Обложка для {group}. Цвета {colors}. Крупный русский текст."
    context.user_data['vk_generated_prompt'] = generated
    await update.message.reply_text("✅ Промпт готов! Выберите элемент упаковки:", reply_markup=get_vk_package_keyboard())
    return VK_PACKAGE_MENU

async def vk_package_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    group = context.user_data.get('vk_group_name', '')
    theme = context.user_data.get('vk_theme', '')
    services = context.user_data.get('vk_services', '')
    advantages = context.user_data.get('vk_advantages', '')
    colors = context.user_data.get('vk_colors', '')
    base = context.user_data.get('vk_generated_prompt', '')
    items = [s.strip() for s in services.split(',') if s.strip()]
    products = items[:5] if len(items) > 5 else items[:3]
    services_list = items[5:] if len(items) > 5 else items[3:]
    prod_text = ", ".join([p.upper() for p in products]) or "ТОВАРЫ"
    serv_text = ", ".join([s.upper() for s in services_list]) or "УСЛУГИ"

    if text == "🖥 Обложка ПК (1920×768)":
        w, h, aspect, elem = 1920, 768, "2.5:1", "обложку ПК"
    elif text == "📱 Мобильная обложка (1080×1920)":
        w, h, aspect, elem = 1080, 1920, "9:16", "мобильную обложку"
    elif text == "🔘 Кнопки меню (376×256)":
        prompt = f"Кнопка меню ВК. Название {group}. Цвета {colors}. Размер 376×256. Одна кнопка, русский текст."
        return await generate_vk_image(update, context, prompt, 376, 256, "кнопку меню")
    elif text == "📊 Виджеты (480×720) ×3":
        return await generate_multiple_widgets(update, context, group, theme, services, colors, advantages)
    elif text == "👤 Аватарка (1080×1080)":
        prompt = f"Аватарка ВК группы '{group}'. Тема {theme}. Цвета {colors}. Размер 1080×1080. Без коллажей."
        return await generate_vk_image(update, context, prompt, 1080, 1080, "аватарку")
    elif text == "🛍 Товары (карточки)":
        prompt = f"Карточки товаров для ВК. Товары: {prod_text}. Цвета {colors}. Размер 800×800."
        return await generate_vk_image(update, context, prompt, 800, 800, "карточки товаров")
    elif text == "📁 Обложка подборки":
        prompt = f"Обложка подборки товаров. Группа {group}. Цвета {colors}. Размер 1200×800."
        return await generate_vk_image(update, context, prompt, 1200, 800, "обложку подборки")
    else:
        await update.message.reply_text("Выберите пункт.", reply_markup=get_vk_package_keyboard())
        return VK_PACKAGE_MENU

    final_prompt = f"{base}\nДетали: {elem}, размер {w}×{h}. Верх 20% пустые. Левый блок: {group}, преимущества {advantages}. Правый блок: товары {prod_text}, услуги {serv_text}. Цвета {colors}. Без коллажей."
    return await generate_vk_image(update, context, final_prompt, w, h, elem)

async def generate_vk_image_raw(update, context, prompt, target_w, target_h, elem_type):
    model = "gpt-image-1-5-text-to-image"
    payload = {"prompt": prompt, "quality": "high"}
    try:
        img_bytes, media_url = await masha_media_generate(model, payload)
        if not img_bytes:
            return None, None
        with Image.open(io.BytesIO(img_bytes)) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb = Image.new('RGB', img.size, (255, 255, 255))
                rgb.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=95)
            return output.getvalue(), media_url
    except Exception as e:
        logger.exception(f"Ошибка {elem_type}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return None, None

async def generate_vk_image(update, context, prompt, width, height, elem_type):
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        bal = get_user_balance(user_id)
        if bal >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Лимит 5/неделю исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Не хватает промтов. Нужно {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    result_bytes, media_url = await generate_vk_image_raw(update, context, prompt, width, height, elem_type)
    if result_bytes:
        compressed = await compress_image(result_bytes, max_size=1920, quality=85)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption=f"🖼 {elem_type}")
        await update.message.reply_text(f"📥 Оригинал: {media_url}")
        if not paid and used < 5:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"VK package: {elem_type}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    else:
        await update.message.reply_text(f"❌ Не удалось создать {elem_type}.")
        if paid:
            add_balance(user_id, PAID_IMAGE_PRICE)
    await update.message.reply_text("Что дальше?", reply_markup=get_vk_package_keyboard())
    return VK_PACKAGE_MENU

async def generate_multiple_widgets(update, context, group, theme, services, colors, advantages):
    user_id = update.effective_user.id
    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        bal = get_user_balance(user_id)
        if bal >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.", reply_markup=get_cancel_keyboard())
            paid = True
        else:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    items = [s.strip() for s in services.split(',') if s.strip()]
    widgets = items[:3] if len(items) >= 3 else items + ["Акция", "Контакты", "О нас"][:3-len(items)]
    for i, wtext in enumerate(widgets, 1):
        prompt = f"Виджет {i} для ВК. Размер 480×720. Группа {group}. Тема {theme}. Цвета {colors}. Содержание {wtext}. Преимущества {advantages}. Крупный русский текст. Без коллажей."
        result, url = await generate_vk_image_raw(update, context, prompt, 480, 720, f"виджет {i}")
        if result:
            compressed = await compress_image(result, max_size=1920, quality=85)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption=f"📊 Виджет {i}")
            await update.message.reply_text(f"📥 Оригинал: {url}")
            if not paid and i == 1 and used < 5:
                increment_weekly_image_count(user_id)
        else:
            await update.message.reply_text(f"❌ Виджет {i} не удался.")
    await update.message.reply_text("Все виджеты готовы!", reply_markup=get_vk_package_keyboard())
    return VK_PACKAGE_MENU

# ------------------- Платежи и веб-сервер -------------------
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
    await update.message.reply_text(f"✅ Баланс пополнен на {amount} промтов!", reply_markup=get_main_keyboard())

async def inline_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "topup":
        await send_topup_invoice(update, context, chat_id=query.message.chat_id)

async def inline_robokassa_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("100 ₽", callback_data="robokassa_100")],
        [InlineKeyboardButton("250 ₽", callback_data="robokassa_250")],
        [InlineKeyboardButton("500 ₽", callback_data="robokassa_500")],
        [InlineKeyboardButton("1000 ₽", callback_data="robokassa_1000")],
    ])
    await query.message.reply_text("💰 Выберите сумму:", reply_markup=keyboard)

async def handle_robokassa_amount_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    if not data.startswith("robokassa_"):
        return
    try:
        amount = int(data.split("_")[1])
    except:
        await query.message.reply_text("❌ Неверная сумма.")
        return
    if amount < 100:
        await query.message.reply_text("Минимальная сумма 100 руб.")
        return
    inv_id = int(time.time() * 100) % 10**9
    create_robokassa_order(inv_id, user_id, amount)
    link = get_payment_url(inv_id, amount, description=f"Пополнение на {amount} руб.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Оплатить", url=link)]])
    await query.message.reply_text(f"Счёт {amount} руб. создан. Номер {inv_id}", reply_markup=keyboard)

async def run_web_server_with_robokassa(port, bot_instance):
    web_app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    async def robokassa_result(request):
        data = await request.post()
        params = dict(data)
        if not check_result_signature(params):
            return web.Response(text="bad sign", status=400)
        inv_id = int(params.get("InvId"))
        out_sum = float(params.get("OutSum"))
        order = get_robokassa_order(inv_id)
        if not order or order["status"] == "success":
            return web.Response(text=f"OK{inv_id}")
        if abs(order["amount"] - out_sum) > 0.01:
            return web.Response(text="amount mismatch", status=400)
        add_balance(order["user_id"], order["amount"])
        update_robokassa_order_status(inv_id, "success")
        try:
            await bot_instance.send_message(order["user_id"], f"✅ Баланс пополнен на {order['amount']} руб.")
        except:
            pass
        return web.Response(text=f"OK{inv_id}")
    async def robokassa_success(request):
        return web.Response(text="<h1>Оплата успешна</h1>", content_type="text/html")
    async def robokassa_fail(request):
        return web.Response(text="<h1>Оплата отменена</h1>", content_type="text/html")
    web_app.router.add_get('/health', health)
    web_app.router.add_post('/robokassa/result', robokassa_result)
    web_app.router.add_get('/robokassa/success', robokassa_success)
    web_app.router.add_get('/robokassa/fail', robokassa_fail)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server на порту {port}")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await runner.cleanup()
        raise

# ------------------- Запуск -------------------
async def main_async():
    init_db()
    if not TELEGRAM_TOKEN or not MASHA_API_KEY:
        logger.error("Не заданы токены")
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
            VK_PACKAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_name)],
            VK_PACKAGE_THEME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_theme)],
            VK_PACKAGE_SERVICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_services)],
            VK_PACKAGE_ADVANTAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_advantages)],
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

    logger.info("Бот запущен")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main_async())
