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

# ------------------- РљРѕРЅСЃС‚Р°РЅС‚С‹ -------------------
PAID_IMAGE_PRICE = 2
ADMIN_IDS = [466829859]   # Р’Р°С€ Telegram user_id

# ------------------- РЎРѕСЃС‚РѕСЏРЅРёСЏ -------------------
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, EDIT_GEN, AUDIO_GEN, AVATAR_GEN, DIALOG, AWAIT_PROMPT = range(9)
AWAIT_FACE_SWAP_TARGET = 9
AWAIT_FACE_SWAP_SOURCE = 10
AWAIT_IMAGE_FOR_EDIT = 11          # РґР»СЏ img2img
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

# ------------------- Р¦РµРЅС‹ РјРѕРґРµР»РµР№ -------------------
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

# ------------------- РљР»Р°РІРёР°С‚СѓСЂС‹ -------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("вњЏпёЏ Р“РµРЅРµСЂР°С†РёСЏ С‚РµРєСЃС‚Р°")],
        [KeyboardButton("рџ–ј Р“РµРЅРµСЂР°С†РёСЏ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ")],
        [KeyboardButton("рџЋ¬ Р“РµРЅРµСЂР°С†РёСЏ РІРёРґРµРѕ")],
        [KeyboardButton("в­ђ РџРѕРїСѓР»СЏСЂРЅС‹Рµ РјРѕРґРµР»Рё РіРµРЅРµСЂР°С†РёРё")],
        [KeyboardButton("рџЋµ РђСѓРґРёРѕ (РѕР·РІСѓС‡РєР°, СЌС„С„РµРєС‚С‹)")],
        [KeyboardButton("рџ¤– РђРІР°С‚Р°СЂ / Р°РЅРёРјР°С†РёСЏ")],
        [KeyboardButton("рџ§№ РЎР±СЂРѕСЃРёС‚СЊ РґРёР°Р»РѕРі")],
        [KeyboardButton("рџ’° РњРѕР№ Р±Р°Р»Р°РЅСЃ")],
        [KeyboardButton("в­ђ РџРѕРїРѕР»РЅРёС‚СЊ РїСЂРѕРјС‚С‹")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_popular_menu_keyboard():
    keyboard = [
        [KeyboardButton("рџ“ќ 1. Р“РµРЅРµСЂР°С†РёСЏ РїСЂРѕРјС‚РѕРІ РґР»СЏ РёР·РѕР±СЂР°Р¶РµРЅРёР№")],
        [KeyboardButton("рџЋҐ 2. Р“РµРЅРµСЂР°С†РёСЏ РїСЂРѕРјС‚РѕРІ РґР»СЏ РІРёРґРµРѕ")],
        [KeyboardButton("рџ–јпёЏ 3. РћР¶РёРІРёС‚СЊ С„РѕС‚Рѕ")],
        [KeyboardButton("рџЋЁ 4. РўРµРєСЃС‚ РІ РёР·РѕР±СЂР°Р¶РµРЅРёРµ")],
        [KeyboardButton("рџ§№ 5. РЈРґР°Р»РёС‚СЊ С„РѕРЅ")],
        [KeyboardButton("вњЁ 6. РЈР»СѓС‡С€РёС‚СЊ РєР°С‡РµСЃС‚РІРѕ")],
        [KeyboardButton("рџ”„ 7. Р—Р°РјРµРЅРёС‚СЊ Р»РёС†Рѕ")],
        [KeyboardButton("рџЋЁ 8. Р РµРґР°РєС‚РёСЂРѕРІР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ (img2img)")],
        [KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")],
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
        btn_text = f"{label} (Р±РµСЃРїР»Р°С‚РЅРѕ)" if price == 0 else f"{label} ({price} РїСЂРѕРјС‚РѕРІ)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_image_models_keyboard():
    # РўРѕР»СЊРєРѕ text-to-image РјРѕРґРµР»Рё
    models = [
        ("z-image", "Z-Image", 0), ("grok-imagine-text-to-image", "Grok Imagine", 0),
        ("flux-2", "Flux 2", 0), ("nano-banana-2", "Nano Banana 2", 0),
        ("nano-banana-pro", "Nano Banana Pro", 0), ("midjourney", "Midjourney", 0),
        ("gpt-image-1-5-text-to-image", "GPT Image 1.5 (txt2img)", 0)
    ]
    keyboard = []
    for model_id, label, price in models:
        keyboard.append([KeyboardButton(f"{label} (Р±РµСЃРїР»Р°С‚РЅРѕ)")])
    keyboard.append([KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")])
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
        keyboard.append([KeyboardButton(f"{label} ({price} РїСЂРѕРјС‚РѕРІ)")])
    keyboard.append([KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_audio_models_keyboard():
    models = [
        ("elevenlabs-tts-multilingual-v2", "РћР·РІСѓС‡РєР° (Multilingual)", 0),
        ("elevenlabs-tts-turbo-2-5", "Р‘С‹СЃС‚СЂР°СЏ РѕР·РІСѓС‡РєР° (Turbo)", 0),
        ("elevenlabs-text-to-dialogue-v3", "Р”РёР°Р»РѕРіРё (Dialogue V3)", 0),
        ("elevenlabs-sound-effect-v2", "Р—РІСѓРєРѕРІС‹Рµ СЌС„С„РµРєС‚С‹ (Sound Effect V2)", 5)
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        if price == 0:
            keyboard.append([KeyboardButton(f"{label} (Р±РµСЃРїР»Р°С‚РЅРѕ)")])
        else:
            keyboard.append([KeyboardButton(f"{label} ({price} РїСЂРѕРјС‚РѕРІ)")])
    keyboard.append([KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_avatar_models_keyboard():
    models = [
        ("kling-v1-avatar-standard", "Kling Avatar Standard", 8),
        ("kling-v1-avatar-pro", "Kling Avatar Pro", 16),
        ("infinitalk-from-audio", "Infinitalk (РіРѕРІРѕСЂСЏС‰Р°СЏ РіРѕР»РѕРІР°)", 1.1),
        ("wan-2-2-animate-move", "Wan Animate Move", 0.75),
        ("wan-2-2-animate-replace", "Wan Animate Replace", 0.75)
    ]
    models.sort(key=lambda x: x[2])
    keyboard = []
    for model_id, label, price in models:
        keyboard.append([KeyboardButton(f"{label} ({price} РїСЂРѕРјС‚РѕРІ)")])
    keyboard.append([KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("рџ”™ Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")]],
        resize_keyboard=True, one_time_keyboard=True
    )

# ------------------- Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ С„СѓРЅРєС†РёРё -------------------
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
            logger.error(f"РћС€РёР±РєР° СЃРѕР·РґР°РЅРёСЏ Р·Р°РґР°С‡Рё {model}: {e}")
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
                    logger.error(f"РЎС‚Р°С‚СѓСЃ {resp.status}, С‚РµР»Рѕ: {text[:200]}")
                    return text
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"РћС‚РІРµС‚ РЅРµ JSON: {text[:200]}")
                    return text
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїРѕР»СѓС‡РµРЅРёСЏ СЃС‚Р°С‚СѓСЃР° {task_id}: {e}")
        return None

async def wait_for_task(task_id: str, timeout=300):
    start = asyncio.get_running_loop().time()
    while True:
        data = await get_task_status(task_id)
        if not data:
            await asyncio.sleep(3)
            if asyncio.get_running_loop().time() - start > timeout:
                raise Exception("РўР°Р№РјР°СѓС‚: РЅРµС‚ РѕС‚РІРµС‚Р° РѕС‚ API")
            continue
        if isinstance(data, str):
            if "429" in data or "500" in data:
                await asyncio.sleep(5)
                continue
            raise Exception(f"РћС€РёР±РєР° API: {data[:200]}")
        status = data.get("status")
        if status == "COMPLETED":
            return data
        elif status == "FAILED":
            raise Exception(f"Р—Р°РґР°С‡Р° РїСЂРѕРІР°Р»РёР»Р°СЃСЊ: {data.get('errorMessage')}")
        await asyncio.sleep(2)
        if asyncio.get_running_loop().time() - start > timeout:
            raise Exception(f"РўР°Р№РјР°СѓС‚ {timeout} СЃРµРєСѓРЅРґ")

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
        raise Exception("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ Р·Р°РґР°С‡Сѓ")
    result = await wait_for_task(task_id)
    if not result:
        raise Exception("РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ СЂРµР·СѓР»СЊС‚Р°С‚")
    if not isinstance(result, dict):
        raise Exception(f"РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚ РѕС‚РІРµС‚Р°: {result}")
    outputs = result.get("output", [])
    if not outputs:
        raise Exception("РќРµС‚ output РІ РѕС‚РІРµС‚Рµ")
    if isinstance(outputs[0], dict):
        media_url = outputs[0].get("url")
    elif isinstance(outputs[0], str):
        media_url = outputs[0]
    else:
        raise Exception(f"РќРµРёР·РІРµСЃС‚РЅС‹Р№ С‚РёРї output: {type(outputs[0])}")
    if not media_url:
        raise Exception("РќРµС‚ URL РІ РѕС‚РІРµС‚Рµ")
    async with aiohttp.ClientSession() as session:
        async with session.get(media_url) as resp:
            if resp.status != 200:
                raise Exception(f"РћС€РёР±РєР° СЃРєР°С‡РёРІР°РЅРёСЏ С„Р°Р№Р»Р°: {resp.status}")
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
        # в•ђв•ђв•ђ РР—РњР•РќР•РќРР•: Hailuo 2.3 СЃ РїРѕРґРґРµСЂР¶РєРѕР№ I2V в•ђв•ђв•ђ
        "hailuo-2-3": {
            "prompt": prompt if prompt else "Natural gentle movement, subtle smile, slight head turn",
            "imageUrl": image_url,
            "duration": "6",
            "resolution": "1080P",
            "variant": "standard"
        },
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

# ------------------- РћР±СЂР°Р±РѕС‚С‡РёРєРё -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "рџ¤– *РџСЂРёРІРµС‚! РЇ Р±РѕС‚ СЃ РїРѕРґРґРµСЂР¶РєРѕР№ РР Р”РјРёС‚СЂРёСЏ РЈСЂРµС†РєРѕРіРѕ.*\n\n"
        "вњЏпёЏ РўРµРєСЃС‚ вЂ“ Р±РµСЃРїР»Р°С‚РЅРѕ, Р±РµР· Р»РёРјРёС‚Р°\n"
        "рџ–ј РР·РѕР±СЂР°Р¶РµРЅРёСЏ вЂ“ Р±РµСЃРїР»Р°С‚РЅРѕ, 5 РІ РЅРµРґРµР»СЋ\n"
        "рџЋ¬ Р’РёРґРµРѕ, рџЋµ РђСѓРґРёРѕ, вњЁ РћР±СЂР°Р±РѕС‚РєР° вЂ“ РїР»Р°С‚РЅРѕ (С‚РѕРєРµРЅС‹)\n\n"
        "Р’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ:", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def clear_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    clear_history(update.effective_user.id)
    await update.message.reply_text("РСЃС‚РѕСЂРёСЏ РѕС‡РёС‰РµРЅР°.", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_user_balance(user_id)
    img_used = get_weekly_image_count(user_id)
    img_left = max(0, 5 - img_used)
    
    text = (
        f"рџ‘¤ **Р’Р°С€ ID:** `{user_id}`\n"
        f"рџ’° **Р‘Р°Р»Р°РЅСЃ:** {bal} РїСЂРѕРјС‚РѕРІ\n"
        f"рџ–ј **Р‘РµСЃРїР»Р°С‚РЅС‹Рµ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ:** {img_used}/5 РёСЃРїРѕР»СЊР·РѕРІР°РЅРѕ РЅР° СЌС‚РѕР№ РЅРµРґРµР»Рµ (РѕСЃС‚Р°Р»РѕСЃСЊ {img_left})\n"
        f"рџ’Ћ **РџР»Р°С‚РЅРѕРµ РёР·РѕР±СЂР°Р¶РµРЅРёРµ** (РїРѕСЃР»Рµ Р»РёРјРёС‚Р°): {PAID_IMAGE_PRICE} РїСЂРѕРјС‚РѕРІ\n\n"
        f"рџ“ћ **РџРѕ РІРѕРїСЂРѕСЃР°Рј:** [РќР°РїРёСЃР°С‚СЊ СЃРѕР·РґР°С‚РµР»СЋ](https://t.me/Dmitriy_Uretskiy)"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("в­ђ РџРѕРїРѕР»РЅРёС‚СЊ РїСЂРѕРјС‚С‹ (Stars)", callback_data="topup")],
        [InlineKeyboardButton("рџ’і РџРѕРїРѕР»РЅРёС‚СЊ С‡РµСЂРµР· Р РѕР±РѕРєР°СЃСЃСѓ", callback_data="robokassa_topup")],
        [InlineKeyboardButton("рџ“ћ РџРѕРґРґРµСЂР¶РєР°", url="https://t.me/Dmitriy_Uretskiy")]
    ])
    
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
