import asyncio
import io
import logging
import os
from typing import List, Tuple

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, PreCheckoutQueryHandler,
    CallbackQueryHandler
)
from telegram.constants import ChatAction
from PIL import Image

from config import TELEGRAM_TOKEN, BOTHUB_API_KEY
from database import (
    init_db, save_message, get_history, clear_history, update_user_activity,
    get_user_balance, add_balance, deduct_balance,
    get_weekly_image_count, increment_weekly_image_count
)
from bothub_client import (
    bothub_text_generate,
    bothub_image_generate,
    bothub_video_generate,
    bothub_animate_photo,
    bothub_image_edit,
    bothub_remove_background,
    bothub_upscale,
    bothub_face_swap,
    bothub_avatar,
    bothub_audio_generate
)

# Robokassa (опционально)
from robokassa import get_payment_url, check_result_signature, check_success_signature
from database import create_robokassa_order, update_robokassa_order_status, get_robokassa_order

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ------------------- Константы -------------------
PAID_IMAGE_PRICE = 2
ADMIN_IDS = [466829859]   # замените на свой user_id

# Состояния ConversationHandler
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, EDIT_GEN, AUDIO_GEN, AVATAR_GEN, DIALOG, AWAIT_PROMPT = range(9)
AWAIT_FACE_SWAP_TARGET, AWAIT_FACE_SWAP_SOURCE, AWAIT_IMAGE_FOR_EDIT, AWAIT_PROMPT_FOR_EDIT = 9, 10, 11, 12
AWAIT_IMAGE_FOR_AVATAR, AWAIT_AUDIO_FOR_AVATAR, AWAIT_VIDEO_FOR_ANIMATE, AWAIT_IMAGE_FOR_ANIMATE, AWAIT_IMAGE_ONLY = 13, 14, 15, 16, 17
POPULAR_MENU, AWAIT_PROMPT_FOR_IMAGE, AWAIT_PHOTO_FOR_ANIMATE, AWAIT_MODE_FOR_ANIMATE, AWAIT_PROMPT_FOR_ANIMATE, AWAIT_PROMPT_FOR_DEEPSEEK = 18, 19, 20, 21, 22, 23

# ------------------- Текстовые модели (Bothub OpenAI) -------------------
TEXT_MODELS = {
    "gpt-4o-mini": "GPT-4o mini (бесплатно)",
    "deepseek-chat": "DeepSeek Chat (бесплатно)",
    "gpt-4o": "GPT-4o (платно: 10 промтов)",
    "claude-sonnet-4-5": "Claude Sonnet 4.5 (платно: 15 промтов)",
    "gemini-2.0-flash": "Gemini 2.0 Flash (бесплатно)",
}
TEXT_MODEL_PRICES = {"gpt-4o": 10, "claude-sonnet-4-5": 15}
for m in TEXT_MODELS:
    if m not in TEXT_MODEL_PRICES:
        TEXT_MODEL_PRICES[m] = 0

# ------------------- Модели изображений (Bothub Replicate) -------------------
IMAGE_MODELS = {
    "flux-schnell": "Flux Schnell (самый дешёвый, качество среднее)",
    "flux-1.1-pro": "Flux 1.1 Pro (качество/цена)",
    "stable-diffusion-3.5-large-turbo": "SD 3.5 Large Turbo (быстрый)",
    "flux-1.1-pro-ultra": "Flux Ultra (максимальное качество, дороже)",
}
IMAGE_MODEL_PRICES = {"flux-schnell": 0, "flux-1.1-pro": 0, "stable-diffusion-3.5-large-turbo": 0, "flux-1.1-pro-ultra": 2}

# ------------------- Модели видео (Bothub Replicate) -------------------
VIDEO_MODELS = {
    "veo-3-fast": "Veo 3 Fast (дешёвый, 1 промт)",
    "sora-2": "Sora 2 (3 промта)",
    "kling-v3-video": "Kling v3 (6 промтов)",
}
VIDEO_MODEL_PRICES = {"veo-3-fast": 1, "sora-2": 3, "kling-v3-video": 6}

# ------------------- Специальные модели для популярного меню -------------------
POPULAR_TEXT_MODEL = "gpt-4o"               # качественный текст
POPULAR_IMAGE_MODEL = "flux-1.1-pro-ultra" # лучшее качество
POPULAR_EDIT_MODEL = "flux-kontext-pro"    # редактирование
POPULAR_ANIMATE_MODEL = "grok-imagine-image-to-video"

# ------------------- Клавиатуры (полный набор) -------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Генерация текста")],
        [KeyboardButton("🖼 Генерация изображения")],
        [KeyboardButton("🎬 Генерация видео")],
        [KeyboardButton("⭐ Популярные модели генерации")],
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
        [KeyboardButton("✏️ 5. Изменить изображение по описанию")],
        [KeyboardButton("🧹 6. Удалить фон")],
        [KeyboardButton("✨ 7. Улучшить качество")],
        [KeyboardButton("🔄 8. Заменить лицо")],
        [KeyboardButton("🔙 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_text_models_keyboard():
    keyboard = []
    for model_id, label in TEXT_MODELS.items():
        keyboard.append([KeyboardButton(label)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_image_models_keyboard():
    keyboard = []
    for model_id, label in IMAGE_MODELS.items():
        keyboard.append([KeyboardButton(label)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_video_models_keyboard():
    keyboard = []
    for model_id, label in VIDEO_MODELS.items():
        keyboard.append([KeyboardButton(label)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_audio_models_keyboard():
    # Временно недоступно
    keyboard = [[KeyboardButton("🔙 Главное меню")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_avatar_models_keyboard():
    # Временно недоступно
    keyboard = [[KeyboardButton("🔙 Главное меню")]]
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

# ------------------- Обработчики -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "🤖 *Привет! Я бот на базі Bothub API.*\n\n"
        "✏️ Текст – бесплатно, без лимита\n"
        "🖼 Изображення – бесплатно, 5 в неделю, далее платно\n"
        "🎬 Видео – платно (промты)\n"
        "🎵 Аудио, 🤖 Аватар – временно недоступны\n\n"
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
        f"🖼 **Бесплатные изображения:** {img_used}/5 на этой неделе (осталось {img_left})\n"
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
        await update.message.reply_text("⛔ У вас нет прав.")
        return
    try:
        target_user_id = int(context.args[0])
        amount = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Используйте: /add_balance <user_id> <количество>")
        return
    add_balance(target_user_id, amount)
    new_balance = get_user_balance(target_user_id)
    await update.message.reply_text(f"✅ Пользователю `{target_user_id}` начислено {amount} промтов. Новый баланс: {new_balance}.", parse_mode="Markdown")

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
        start_parameter="topup",
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False
    )

# ------------------- Главное меню -------------------
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
    elif text == "🎵 Аудио (озвучка, эффекты)":
        await update.message.reply_text("🎵 Функция временно недоступна в Bothub. Пожалуйста, используйте другие функции.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    elif text == "🤖 Аватар / анимация":
        await update.message.reply_text("🤖 Функция временно недоступна в Bothub. Используйте «Оживить фото» в популярном меню.", reply_markup=get_main_keyboard())
        return MAIN_MENU
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

# ------------------- Выбор модели (текст, изображение, видео) -------------------
async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Текст
    for model_id, label in TEXT_MODELS.items():
        if text.strip() == label:
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = TEXT_MODEL_PRICES.get(model_id, 0)
            context.user_data['media_category'] = 'text'
            await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
            return DIALOG

    # Изображения
    for model_id, label in IMAGE_MODELS.items():
        if text.strip() == label:
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = IMAGE_MODEL_PRICES.get(model_id, 0)
            context.user_data['media_category'] = 'image'
            await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите описание:", reply_markup=get_cancel_keyboard())
            return AWAIT_PROMPT

    # Видео
    for model_id, label in VIDEO_MODELS.items():
        if text.strip() == label:
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = VIDEO_MODEL_PRICES.get(model_id, 0)
            context.user_data['media_category'] = 'video'
            await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите описание видео:", reply_markup=get_cancel_keyboard())
            return AWAIT_PROMPT

    await update.message.reply_text("Пожалуйста, выберите модель из списка.", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Диалог (текст) -------------------
async def start_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str = None) -> int:
    user_id = update.effective_user.id
    if user_message is None:
        user_message = update.message.text
    if user_message == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'gpt-4o-mini')
    price = context.user_data.get('model_price', 0)

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
        answer = await bothub_text_generate(user_message, history, model)
    except Exception as e:
        answer = None
        logger.exception("Текстовая ошибка")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if price > 0:
            add_balance(user_id, price)
        return MAIN_MENU
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

# ------------------- Обработчик для одношаговой генерации (изображение или видео) -------------------
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

    # Проверка баланса и лимитов
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
                await update.message.reply_text(f"⚠️ Бесплатный лимит (5/неделю) исчерпан. Списано {PAID_IMAGE_PRICE} промтов.")
                paid = True
            else:
                await update.message.reply_text(f"❌ Бесплатный лимит исчерпан. Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
                return MAIN_MENU
    elif price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    action = ChatAction.UPLOAD_PHOTO if category == "image" else (ChatAction.UPLOAD_VIDEO if category == "video" else ChatAction.TYPING)
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, action, stop_action))
    try:
        if category == "image":
            result_bytes, media_url = await bothub_image_generate(prompt, model)
        elif category == "video":
            result_bytes, media_url = await bothub_video_generate(prompt, model)
        else:
            raise Exception("Неизвестная категория")
    except Exception as e:
        logger.exception("Ошибка генерации")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        if category == "video":
            await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🎬 Результат")
        else:
            compressed = await compress_image(result_bytes)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат (сжатое)")
            await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
            if category == "image" and price == 0 and used < 5 and not paid:
                increment_weekly_image_count(user_id)
        save_message(user_id, "user", f"{category} запрос: {prompt}")
        save_message(user_id, "assistant", "Контент сгенерирован")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Популярное меню (качественные модели) -------------------
async def handle_popular_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    elif text == "📝 1. Генерация промтов для изображений":
        context.user_data['pending_action'] = 'prompt_image'
        await update.message.reply_text("Опишите, что вы хотите изобразить:", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_DEEPSEEK

    elif text == "🎥 2. Генерация промтов для видео":
        context.user_data['pending_action'] = 'prompt_video'
        await update.message.reply_text("Опишите сюжет видео:", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_DEEPSEEK

    elif text == "🖼️ 3. Оживить фото":
        context.user_data['pending_action'] = 'animate_photo'
        await update.message.reply_text("Отправьте фото (JPEG/PNG):", reply_markup=get_cancel_keyboard())
        return AWAIT_PHOTO_FOR_ANIMATE

    elif text == "🎨 4. Текст в изображение":
        context.user_data['selected_model'] = POPULAR_IMAGE_MODEL
        context.user_data['model_price'] = IMAGE_MODEL_PRICES.get(POPULAR_IMAGE_MODEL, 0)
        context.user_data['media_category'] = 'image'
        await update.message.reply_text("Введите описание изображения:", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_IMAGE

    elif text == "✏️ 5. Изменить изображение по описанию":
        context.user_data['selected_model'] = POPULAR_EDIT_MODEL
        context.user_data['model_price'] = 2  # цена как у flux-1.1-pro-ultra
        context.user_data['media_category'] = 'image'
        await update.message.reply_text(
            "🔹 Редактирование изображения\n\n"
            "1️⃣ Отправьте **изображение**, которое хотите изменить\n"
            "2️⃣ Затем отправьте **текстовое описание** изменений\n\n"
            "Отправьте первое фото:",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_IMAGE_FOR_EDIT

    elif text == "🧹 6. Удалить фон":
        await update.message.reply_text("⛔ Удаление фона временно недоступно в Bothub. Рекомендуем сгенерировать новое изображение с нужным фоном.", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU

    elif text == "✨ 7. Улучшить качество":
        await update.message.reply_text("⛔ Улучшение качества (апскейл) временно недоступно в Bothub.", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU

    elif text == "🔄 8. Заменить лицо":
        await update.message.reply_text("⛔ Замена лица временно недоступна в Bothub.", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU

    else:
        await update.message.reply_text("Пожалуйста, выберите пункт из меню.", reply_markup=get_popular_menu_keyboard())
        return POPULAR_MENU

# ------------------- Генерация промтов через текстовую модель (качественную) -------------------
async def handle_deepseek_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_input = update.message.text
    if user_input == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    action = context.user_data.get('pending_action')
    if action == 'prompt_image':
        system_prompt = "Ты — эксперт по созданию промтов для изображений. Напиши подробный промт на русском (50-200 слов). Только промт."
        user_prompt = f"Создай промт для изображения по запросу: {user_input}"
    elif action == 'prompt_video':
        system_prompt = "Ты — эксперт по созданию промтов для видео. Напиши подробный промт на русском (50-200 слов). Только промт."
        user_prompt = f"Создай промт для видео по запросу: {user_input}"
    else:
        await update.message.reply_text("Ошибка.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    fake_history = [("system", system_prompt)]
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.TYPING, stop_action))
    try:
        answer = await bothub_text_generate(user_prompt, fake_history, POPULAR_TEXT_MODEL)
    finally:
        stop_action.set()
        await action_task

    if answer:
        await update.message.reply_text(f"✨ **Сгенерированный промт:**\n\n{answer}", parse_mode="Markdown")
        save_message(user_id, "assistant", answer)
    else:
        await update.message.reply_text("❌ Не удалось сгенерировать промт.")
    await update.message.reply_text("Продолжайте работу:", reply_markup=get_popular_menu_keyboard())
    context.user_data.pop('pending_action', None)
    return POPULAR_MENU

# ------------------- Текст в изображение (качественное) -------------------
async def handle_text_to_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    prompt = update.message.text
    if prompt == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = POPULAR_IMAGE_MODEL
    price = IMAGE_MODEL_PRICES.get(model, 0)

    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.")
            paid = True
        else:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    elif price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await bothub_image_generate(prompt, model)
    except Exception as e:
        logger.exception("Ошибка генерации изображения")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)
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
        if paid or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Оживление фото -------------------
async def handle_animate_photo_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        if update.message.text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте фото.", reply_markup=get_cancel_keyboard())
            return AWAIT_PHOTO_FOR_ANIMATE
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фото.", reply_markup=get_cancel_keyboard())
        return AWAIT_PHOTO_FOR_ANIMATE

    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    context.user_data['animate_photo_url'] = photo_url

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("Normal"), KeyboardButton("Fun")], [KeyboardButton("🔙 Главное меню")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "Фото получено. Выберите режим анимации:\n"
        "• Normal – естественное движение\n"
        "• Fun – весёлое\n\n"
        "Затем можно добавить текстовое описание ('пропустить' – без описания).",
        reply_markup=keyboard
    )
    return AWAIT_MODE_FOR_ANIMATE

async def handle_animate_photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if text in ("Normal", "Fun"):
        context.user_data['animate_mode'] = text.lower()
        await update.message.reply_text("Теперь отправьте описание движения или напишите 'пропустить':", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT_FOR_ANIMATE
    else:
        await update.message.reply_text("Выберите Normal или Fun.", reply_markup=get_cancel_keyboard())
        return AWAIT_MODE_FOR_ANIMATE

async def handle_animate_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    photo_url = context.user_data.get('animate_photo_url')
    mode = context.user_data.get('animate_mode', 'normal')
    prompt = None if text.lower() == "пропустить" else text

    price = 1  # цена для анимации
    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))
    try:
        result_bytes, media_url = await bothub_animate_photo(photo_url, mode, prompt)
    except Exception as e:
        logger.exception("Ошибка оживления фото")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🖼️ Оживлённое видео")
        await update.message.reply_text(f"📥 Скачать оригинал: {media_url}")
        save_message(user_id, "user", f"animate photo: mode={mode}, prompt={prompt}")
        save_message(user_id, "assistant", "Видео создано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Редактирование изображения по описанию -------------------
async def handle_edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text:
        if update.message.text == "🔙 Главное меню":
            context.user_data.clear()
            await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение.", reply_markup=get_cancel_keyboard())
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

    model = POPULAR_EDIT_MODEL
    price = 2
    user_id = update.effective_user.id

    used = get_weekly_image_count(user_id)
    paid = False
    if used >= 5:
        balance = get_user_balance(user_id)
        if balance >= PAID_IMAGE_PRICE:
            if not deduct_balance(user_id, PAID_IMAGE_PRICE):
                await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                return MAIN_MENU
            await update.message.reply_text(f"⚠️ Бесплатный лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.")
            paid = True
        else:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {PAID_IMAGE_PRICE}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
    elif price > 0:
        if get_user_balance(user_id) < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_PHOTO, stop_action))
    try:
        result_bytes, media_url = await bothub_image_edit(image_url, prompt_text, model)
    except Exception as e:
        logger.exception("Ошибка редактирования")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        if paid or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)
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
        save_message(user_id, "user", f"edit image: {prompt_text}")
        save_message(user_id, "assistant", "Изображение отредактировано")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if paid or price > 0:
            add_balance(user_id, price if price > 0 else PAID_IMAGE_PRICE)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- Обработчики платежей -------------------
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
    await update.message.reply_text(f"✅ Баланс пополнен на {amount} промтов! Теперь у вас {get_user_balance(user_id)} промтов.", reply_markup=get_main_keyboard())

async def inline_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "topup":
        await send_topup_invoice(update, context, chat_id=query.message.chat_id)

# ------------------- Веб-сервер для Robokassa -------------------
async def run_web_server_with_robokassa(port, bot_instance):
    from aiohttp import web
    web_app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    async def robokassa_result(request):
        data = await request.post()
        params = dict(data)
        logger.info(f"Robokassa result: {params}")
        if not check_result_signature(params):
            return web.Response(text="bad sign", status=400)
        inv_id = int(params.get("InvId"))
        out_sum = float(params.get("OutSum"))
        order = get_robokassa_order(inv_id)
        if not order:
            return web.Response(text="Order not found", status=404)
        if order["status"] == "success":
            return web.Response(text=f"OK{inv_id}")
        if abs(order["amount"] - out_sum) > 0.01:
            return web.Response(text="amount mismatch", status=400)
        add_balance(order["user_id"], order["amount"])
        update_robokassa_order_status(inv_id, "success")
        try:
            await bot_instance.send_message(chat_id=order["user_id"], text=f"✅ Баланс пополнен на {order['amount']} промтов через Robokassa!")
        except:
            pass
        return web.Response(text=f"OK{inv_id}")
    async def robokassa_success(request):
        params = dict(request.query)
        if not check_success_signature(params):
            return web.Response(text="bad sign", status=400)
        return web.Response(text="<h1>Оплата успешна</h1>", content_type="text/html")
    async def robokassa_fail(request):
        return web.Response(text="<h1>Оплата не удалась</h1>", content_type="text/html")
    web_app.router.add_get('/health', health)
    web_app.router.add_post('/robokassa/result', robokassa_result)
    web_app.router.add_get('/robokassa/success', robokassa_success)
    web_app.router.add_get('/robokassa/fail', robokassa_fail)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server запущен на порту {port}")
    await asyncio.Event().wait()

# ------------------- Запуск -------------------
async def main_async():
    init_db()
    if not TELEGRAM_TOKEN or not BOTHUB_API_KEY:
        logger.error("Не заданы TELEGRAM_TOKEN или BOTHUB_API_KEY")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu),
                CallbackQueryHandler(lambda u,c: None, pattern="robokassa_topup"),  # заглушка будет позже
                CallbackQueryHandler(lambda u,c: None, pattern="^robokassa_\\d+$"),
            ],
            TEXT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            VIDEO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_model_selection)],
            DIALOG: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_dialog)],
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media_input)],
            AWAIT_IMAGE_FOR_EDIT: [MessageHandler(filters.PHOTO, handle_edit_image), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_image)],
            AWAIT_PROMPT_FOR_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_prompt)],
            POPULAR_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_popular_menu)],
            AWAIT_PROMPT_FOR_DEEPSEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deepseek_prompt)],
            AWAIT_PROMPT_FOR_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_to_image)],
            AWAIT_PHOTO_FOR_ANIMATE: [MessageHandler(filters.PHOTO, handle_animate_photo_photo), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_photo)],
            AWAIT_MODE_FOR_ANIMATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_mode)],
            AWAIT_PROMPT_FOR_ANIMATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_prompt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(CommandHandler("add_balance", add_balance_command))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(inline_topup_callback, pattern="topup"))

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

if __name__ == "__main__":
    main()
