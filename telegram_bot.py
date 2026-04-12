import asyncio
import io
import json
import logging
import os
from typing import List, Tuple

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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

from PIL import Image

# ------------------- Константы -------------------
PAID_IMAGE_PRICE = 2

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

# ------------------- Цены моделей -------------------
MODEL_PRICES = {
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
    "elevenlabs-tts-multilingual-v2": 0,
    "elevenlabs-tts-turbo-2-5": 0,
    "elevenlabs-text-to-dialogue-v3": 0,
    "elevenlabs-sound-effect-v2": 5,
    "kling-v1-avatar-pro": 16,
    "kling-v1-avatar-standard": 8,
    "infinitalk-from-audio": 1.1,
    "wan-2-2-animate-move": 0.75,
    "wan-2-2-animate-replace": 0.75,
}

# Типы входных данных для моделей
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
        ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
        ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
        ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
        ("recraft-remove-background", "Recraft Remove Background", 0),
        ("topaz-image-upscale", "Topaz Image Upscale", 0), ("flux-2", "Flux 2", 0),
        ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0), ("nano-banana-2", "Nano Banana 2", 0),
        ("nano-banana-pro", "Nano Banana Pro", 0), ("midjourney", "Midjourney", 0),
        ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0),
        ("gpt-image-1-5-image-to-image", "GPT Image 1.5 (img2img)", 0),
        ("ideogram-v3-reframe", "Ideogram V3 Reframe", 0)
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

def get_edit_models_keyboard():
    models = [
        ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
        ("recraft-remove-background", "Recraft Remove Background", 0),
        ("topaz-image-upscale", "Topaz Image Upscale", 0),
        ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
        ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
        ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0)
    ]
    keyboard = []
    for model_id, label, price in models:
        keyboard.append([KeyboardButton(f"{label} (бесплатно)")])
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
        "🤖 *Привет! Я бот с поддержью ИИ (MashaGPT).*\n\n"
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
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Пополнить промты", callback_data="topup")]])
    await update.message.reply_text(
        f"💰 Ваш баланс: {bal} промтов\n"
        f"🖼 Бесплатные изображения: {img_used}/5 использовано на этой неделе\n"
        f"   Осталось бесплатных: {img_left}\n"
        f"💎 Платное изображение (после лимита): {PAID_IMAGE_PRICE} промтов",
        reply_markup=keyboard
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
    elif text == "✨ Обработка изображений":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель обработки:", reply_markup=get_edit_models_keyboard())
        return EDIT_GEN
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

async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if category == "text":
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
    elif category == "image":
        models = [
            ("z-image", "Z-Image", 0), ("grok-imagine-text-to-image", "Grok Imagine", 0),
            ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
            ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
            ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
            ("recraft-remove-background", "Recraft Remove Background", 0),
            ("topaz-image-upscale", "Topaz Image Upscale", 0), ("flux-2", "Flux 2", 0),
            ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0), ("nano-banana-2", "Nano Banana 2", 0),
            ("nano-banana-pro", "Nano Banana Pro", 0), ("midjourney", "Midjourney", 0),
            ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0),
            ("gpt-image-1-5-image-to-image", "GPT Image 1.5 (img2img)", 0),
            ("ideogram-v3-reframe", "Ideogram V3 Reframe", 0)
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
            ("kling-2-6-motion-control", "Kling 2.6 Motion Control", 6)
        ]
    elif category == "edit":
        models = [
            ("recraft-crisp-upscale", "Recraft Crisp Upscale", 0),
            ("recraft-remove-background", "Recraft Remove Background", 0),
            ("topaz-image-upscale", "Topaz Image Upscale", 0),
            ("codeplugtech-face-swap", "Face Swap (CodePlugTech)", 0),
            ("cdlingram-face-swap", "Face Swap (CDIngram)", 0),
            ("qwen-edit-multiangle", "Qwen Edit Multiangle", 0)
        ]
    elif category == "audio":
        models = [
            ("elevenlabs-tts-multilingual-v2", "Озвучка (Multilingual)", 0),
            ("elevenlabs-tts-turbo-2-5", "Быстрая озвучка (Turbo)", 0),
            ("elevenlabs-text-to-dialogue-v3", "Диалоги (Dialogue V3)", 0),
            ("elevenlabs-sound-effect-v2", "Звуковые эффекты (Sound Effect V2)", 5)
        ]
    elif category == "avatar":
        models = [
            ("kling-v1-avatar-standard", "Kling Avatar Standard", 8),
            ("kling-v1-avatar-pro", "Kling Avatar Pro", 16),
            ("infinitalk-from-audio", "Infinitalk (говорящая голова)", 1.1),
            ("wan-2-2-animate-move", "Wan Animate Move", 0.75),
            ("wan-2-2-animate-replace", "Wan Animate Replace", 0.75)
        ]
    else:
        models = []

    for model_id, label, price in models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = category
            context.user_data['media_category'] = category

            input_type = MODEL_INPUT_TYPE.get(model_id, ("text",))

            if input_type == ("text",):
                if category == "text":
                    await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
                    return DIALOG
                else:
                    await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
                    return AWAIT_PROMPT
            elif input_type == ("image", "image"):
                context.user_data['awaiting'] = 'face_swap_target'
                await update.message.reply_text(
                    f"🔹 Модель: {label}\n"
                    f"Что делает: заменяет лицо на целевом фото.\n\n"
                    f"1️⃣ Отправьте **целевое изображение** (куда вставить лицо)\n"
                    f"2️⃣ Затем отправьте **изображение-источник лица**\n\n"
                    f"Отправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_FACE_SWAP_TARGET
            elif input_type == ("image", "text"):
                context.user_data['awaiting'] = 'edit_image'
                await update.message.reply_text(
                    f"🔹 Модель: {label}\n"
                    f"Что делает: редактирует изображение по вашему описанию.\n\n"
                    f"1️⃣ Отправьте **изображение**, которое хотите изменить\n"
                    f"2️⃣ Затем отправьте **текстовое описание** изменений\n\n"
                    f"Отправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_FOR_EDIT
            elif input_type == ("image", "audio"):
                context.user_data['awaiting'] = 'avatar_image'
                await update.message.reply_text(
                    f"🔹 Модель: {label}\n"
                    f"Что делает: создаёт видео, где лицо с фото говорит текст из аудио.\n\n"
                    f"1️⃣ Отправьте **фото лица** (чёткое, анфас)\n"
                    f"2️⃣ Затем отправьте **аудиофайл** (MP3/WAV) с речью\n\n"
                    f"Отправьте первое фото:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_FOR_AVATAR
            elif input_type == ("video", "image"):
                context.user_data['awaiting'] = 'animate_video'
                await update.message.reply_text(
                    f"🔹 Модель: {label}\n"
                    f"Что делает: переносит движение из видео на ваше изображение.\n\n"
                    f"1️⃣ Отправьте **видео-референс** (движение)\n"
                    f"2️⃣ Затем отправьте **изображение персонажа**\n\n"
                    f"Отправьте первое видео:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_VIDEO_FOR_ANIMATE
            elif input_type == ("image",):
                await update.message.reply_text(
                    f"🔹 Модель: {label}\n"
                    f"Что делает: обрабатывает одно изображение.\n\n"
                    f"Отправьте **изображение**:",
                    reply_markup=get_cancel_keyboard()
                )
                return AWAIT_IMAGE_ONLY
            else:
                await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
                return AWAIT_PROMPT

    await update.message.reply_text("Пожалуйста, выберите модель из списка.")
    return MAIN_MENU

async def handle_text_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "text")

async def handle_image_selection(update, context):
    return await handle_model_selection(update, context, "image")

async def handle_video_selection(update, context):
    return await handle_model_selection(update, context, "video")

async def handle_edit_selection(update, context):
    return await handle_model_selection(update, context, "edit")

async def handle_audio_selection(update, context):
    return await handle_model_selection(update, context, "audio")

async def handle_avatar_selection(update, context):
    return await handle_model_selection(update, context, "avatar")

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

async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    model = context.user_data.get('selected_model')
    price = context.user_data.get('model_price', 0)
    category = context.user_data.get('media_category')
    text = update.message.text

    if text.endswith("(бесплатно)") or ("(" in text and "промтов)" in text):
        await update.message.reply_text(
            "📝 Пожалуйста, введите текстовый запрос для генерации.\n"
            "Пример: «кот в космосе» или «реалистичный пейзаж»",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_PROMPT

    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not category or not model:
        await update.message.reply_text("Ошибка: не выбрана категория или модель.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not text or text.isspace():
        await update.message.reply_text("Пожалуйста, введите текст запроса.", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT

    payload = build_payload(model, prompt=text)
    if not payload:
        await update.message.reply_text(f"❌ Не удалось сформировать запрос для модели {model}.")
        return MAIN_MENU

    logger.info(f"Генерация {category} с моделью {model}, payload={payload}")

    if category == "image" and price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            balance = get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(
                    f"⚠️ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Списано {PAID_IMAGE_PRICE} промтов за это изображение.\n"
                    f"Остаток на балансе: {get_user_balance(user_id)} промтов.\n"
                    f"Продолжаем генерацию...",
                    reply_markup=get_cancel_keyboard()
                )
                context.user_data['paid_image'] = True
            else:
                await update.message.reply_text(
                    f"❌ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Недостаточно промтов для платной генерации. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.\n"
                    f"Пополните баланс в личном кабинете.",
                    reply_markup=get_main_keyboard()
                )
                return MAIN_MENU
        else:
            context.user_data['paid_image'] = False

    if price > 0 and category != "image":
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    if category == "text":
        action = ChatAction.TYPING
    elif category in ("image", "edit"):
        action = ChatAction.UPLOAD_PHOTO
    elif category == "video":
        action = ChatAction.UPLOAD_VIDEO
    elif category == "audio":
        action = ChatAction.RECORD_AUDIO
    elif category == "avatar":
        action = ChatAction.UPLOAD_VIDEO
    else:
        action = ChatAction.TYPING

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, action, stop_action))
    result_bytes = None
    media_url = None
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка генерации медиа")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if category == "image" and price == 0 and context.user_data.get('paid_image', False):
            add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            add_balance(user_id, price)
        await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        if category == "video":
            await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🎬 Результат")
        elif category == "audio":
            await update.message.reply_audio(audio=io.BytesIO(result_bytes), title="Аудио", caption="🎵 Готово!")
        elif category == "avatar":
            await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🤖 Аватар готов")
        elif category == "image":
            compressed = await compress_image(result_bytes)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат (сжатое)")
            await update.message.reply_text(f"📥 Скачать оригинал в высоком разрешении: {media_url}")
        else:
            await update.message.reply_photo(photo=io.BytesIO(result_bytes), caption="🖼 Результат")

        if category == "image" and price == 0 and not context.user_data.get('paid_image', False):
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"{category} запрос: {text}")
        save_message(user_id, "assistant", "Контент сгенерирован")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if category == "image" and price == 0 and context.user_data.get('paid_image', False):
            add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Обработчики для многошаговых моделей -------------------
async def handle_face_swap_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text(
                "Пожалуйста, отправьте целевое изображение (фото).",
                reply_markup=get_cancel_keyboard()
            )
            return AWAIT_FACE_SWAP_TARGET

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте целевое изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_FACE_SWAP_TARGET
    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    context.user_data['target_image_url'] = photo_url
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
            await update.message.reply_text(
                "Пожалуйста, отправьте изображение-источник лица.",
                reply_markup=get_cancel_keyboard()
            )
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

    model = context.user_data['selected_model']
    price = context.user_data['model_price']
    user_id = update.effective_user.id
    category = context.user_data.get('selected_category', 'image')

    paid_image = False
    if price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            balance = get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(
                    f"⚠️ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Списано {PAID_IMAGE_PRICE} промтов за это изображение.\n"
                    f"Остаток на балансе: {get_user_balance(user_id)} промтов.\n"
                    f"Продолжаем генерацию...",
                    reply_markup=get_cancel_keyboard()
                )
                paid_image = True
            else:
                await update.message.reply_text(
                    f"❌ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Недостаточно промтов для платной генерации. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.\n"
                    f"Пополните баланс в личном кабинете.",
                    reply_markup=get_main_keyboard()
                )
                return MAIN_MENU
    else:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    image_url = f"{target_url} {swap_url}"
    payload = build_payload(model, prompt=None, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос для замены лица.", reply_markup=get_main_keyboard())
        if price > 0 or (price == 0 and paid_image):
            add_balance(user_id, PAID_IMAGE_PRICE if paid_image else price)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка face-swap")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if price > 0 or (price == 0 and paid_image):
            add_balance(user_id, PAID_IMAGE_PRICE if paid_image else price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат замены лица (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if price == 0 and not paid_image:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"face-swap: target={target_url}, swap={swap_url}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if price > 0 or (price == 0 and paid_image):
            add_balance(user_id, PAID_IMAGE_PRICE if paid_image else price)

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
        "✅ Изображение получено. Теперь отправьте **текстовое описание** изменений:",
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

    model = context.user_data['selected_model']
    price = context.user_data['model_price']
    user_id = update.effective_user.id

    paid_image = False
    if price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            balance = get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(
                    f"⚠️ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Списано {PAID_IMAGE_PRICE} промтов за это изображение.\n"
                    f"Остаток на балансе: {get_user_balance(user_id)} промтов.\n"
                    f"Продолжаем генерацию...",
                    reply_markup=get_cancel_keyboard()
                )
                paid_image = True
            else:
                await update.message.reply_text(
                    f"❌ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Недостаточно промтов для платной генерации. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.\n"
                    f"Пополните баланс в личном кабинете.",
                    reply_markup=get_main_keyboard()
                )
                return MAIN_MENU
    else:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    payload = build_payload(model, prompt=prompt_text, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос.", reply_markup=get_main_keyboard())
        if price > 0 or (price == 0 and paid_image):
            add_balance(user_id, PAID_IMAGE_PRICE if paid_image else price)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка редактирования изображения")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if price > 0 or (price == 0 and paid_image):
            add_balance(user_id, PAID_IMAGE_PRICE if paid_image else price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат редактирования (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        if price == 0 and not paid_image:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"edit image: {prompt_text}")
        save_message(user_id, "assistant", "Изображение отредактировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if price > 0 or (price == 0 and paid_image):
            add_balance(user_id, PAID_IMAGE_PRICE if paid_image else price)

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
            await update.message.reply_text(
                "Пожалуйста, отправьте фото лица (чёткое, анфас).",
                reply_markup=get_cancel_keyboard()
            )
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
            await update.message.reply_text(
                "Пожалуйста, отправьте аудиофайл (MP3/WAV) или голосовое сообщение.",
                reply_markup=get_cancel_keyboard()
            )
            return AWAIT_AUDIO_FOR_AVATAR

    if not update.message.audio and not update.message.voice:
        await update.message.reply_text("Пожалуйста, отправьте аудиофайл (MP3/WAV) или голосовое сообщение.", reply_markup=get_cancel_keyboard())
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

    model = context.user_data['selected_model']
    price = context.user_data['model_price']
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
            await update.message.reply_text(
                "Пожалуйста, отправьте видео-референс (движение).",
                reply_markup=get_cancel_keyboard()
            )
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
            await update.message.reply_text(
                "Пожалуйста, отправьте изображение персонажа.",
                reply_markup=get_cancel_keyboard()
            )
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

    model = context.user_data['selected_model']
    price = context.user_data['model_price']
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

async def handle_single_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        text = update.message.text.strip()
        if text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text(
                "Пожалуйста, отправьте изображение (фото) для обработки.",
                reply_markup=get_cancel_keyboard()
            )
            return AWAIT_IMAGE_ONLY

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_IMAGE_ONLY

    photo_file = await update.message.photo[-1].get_file()
    image_url = photo_file.file_path
    model = context.user_data.get('selected_model')
    price = context.user_data.get('model_price', 0)
    user_id = update.effective_user.id

    paid_image = False
    if price == 0:
        used = get_weekly_image_count(user_id)
        if used >= 5:
            balance = get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания токенов.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(
                    f"⚠️ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Списано {PAID_IMAGE_PRICE} промтов за это изображение.\n"
                    f"Остаток на балансе: {get_user_balance(user_id)} промтов.\n"
                    f"Продолжаем обработку...",
                    reply_markup=get_cancel_keyboard()
                )
                paid_image = True
            else:
                await update.message.reply_text(
                    f"❌ Бесплатный лимит (5/неделю) исчерпан.\n"
                    f"Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}, у вас: {balance}.\n"
                    f"Пополните баланс в разделе «⭐ Пополнить промты».",
                    reply_markup=get_main_keyboard()
                )
                return MAIN_MENU
    else:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    payload = build_payload(model, image_url=image_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос.", reply_markup=get_main_keyboard())
        if price == 0 and paid_image:
            add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            add_balance(user_id, price)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка обработки изображения")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if price == 0 and paid_image:
            add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        compressed = await compress_image(result_bytes)
        await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат (сжатое)")
        await update.message.reply_text(f"📥 Скачать оригинал в высоком разрешении: {media_url}")
        if price == 0 and not paid_image:
            increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"image processing: {model}")
        save_message(user_id, "assistant", "Изображение обработано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if price == 0 and paid_image:
            add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

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

# ------------------- Запуск (webhook или polling) -------------------
async def main_async():
    init_db()
    if not TELEGRAM_TOKEN or not MASHA_API_KEY:
        logger.error("Не заданы TELEGRAM_TOKEN или MASHA_API_KEY")
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
            AWAIT_FACE_SWAP_TARGET: [MessageHandler(filters.PHOTO, handle_face_swap_target),
                                     MessageHandler(filters.TEXT & ~filters.COMMAND, handle_face_swap_target)],
            AWAIT_FACE_SWAP_SOURCE: [MessageHandler(filters.PHOTO, handle_face_swap_source),
                                     MessageHandler(filters.TEXT & ~filters.COMMAND, handle_face_swap_source)],
            AWAIT_IMAGE_FOR_EDIT: [MessageHandler(filters.PHOTO, handle_edit_image),
                                   MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_image)],
            AWAIT_PROMPT_FOR_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_prompt)],
            AWAIT_IMAGE_FOR_AVATAR: [MessageHandler(filters.PHOTO, handle_avatar_image),
                                     MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_image)],
            AWAIT_AUDIO_FOR_AVATAR: [MessageHandler(filters.AUDIO | filters.VOICE, handle_avatar_audio),
                                     MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_audio)],
            AWAIT_VIDEO_FOR_ANIMATE: [MessageHandler(filters.VIDEO, handle_animate_video),
                                      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_video)],
            AWAIT_IMAGE_FOR_ANIMATE: [MessageHandler(filters.PHOTO, handle_animate_image),
                                      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_image)],
            AWAIT_IMAGE_ONLY: [MessageHandler(filters.PHOTO, handle_single_image),
                               MessageHandler(filters.TEXT & ~filters.COMMAND, handle_single_image)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(inline_topup_callback, pattern="topup"))

    port = int(os.getenv("PORT", 8080))
    webhook_url = os.getenv("WEBHOOK_URL")

    if not webhook_url:
        render_url = os.getenv("RENDER_EXTERNAL_URL")
        if render_url:
            webhook_url = f"{render_url}/webhook"
        else:
            webhook_url = None

    if port and webhook_url:
        logger.info(f"Запуск в режиме webhook. URL: {webhook_url}")
        await app.bot.set_webhook(webhook_url)
        await app.run_webhook(listen="0.0.0.0", port=port, webhook_path="/webhook")
    else:
        logger.info("Запуск в режиме polling (локально или без webhook URL)")
        await app.run_polling()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
