import asyncio
import io
import json
import logging
import time
from typing import List, Tuple

import aiohttp
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

from config import (
    TELEGRAM_TOKEN, DEEPSEEK_API_KEY,
    MASHA_API_KEY, MASHA_BASE_URL
)
from database import (
    init_db, save_message, get_history, clear_history, update_user_activity
)

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния ConversationHandler
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, DIALOG = range(5)

# ------------------------------------------------------------------
# Клавиатуры
# ------------------------------------------------------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Генерация текста")],
        [KeyboardButton("🖼 Генерация изображения")],
        [KeyboardButton("🎬 Генерация видео")],
        [KeyboardButton("🧹 Сбросить диалог")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔙 Главное меню")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ------------------------------------------------------------------
# Функции для работы с DeepSeek (текст)
# ------------------------------------------------------------------
async def deepseek_generate(prompt: str, history: List[Tuple[str, str]]) -> str:
    """
    Вызов DeepSeek API с учётом истории.
    history: список кортежей (role, content) – user/assistant.
    """
    messages = []
    # Добавляем историю (последние 5 сообщений)
    for role, content in history[-5:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.7
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"DeepSeek API error {resp.status}: {error_text}")
                raise Exception(f"DeepSeek error: {resp.status}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

# ------------------------------------------------------------------
# Функции для Masha (изображения, видео – остаются как заглушки)
# ------------------------------------------------------------------
async def masha_image_generate(prompt: str) -> bytes:
    """Генерация изображения через Masha Nano Banana"""
    # Если ключ Masha не задан, возвращаем ошибку
    if not MASHA_API_KEY:
        raise Exception("MASHA_API_KEY не задан. Генерация изображений недоступна.")
    url = f"{MASHA_BASE_URL}/images/generations"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": MASHA_API_KEY
    }
    payload = {
        "model": "nano-banana-2",
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "size": "1024x1024"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"Image API error {resp.status}: {error_text}")
                raise Exception(f"Image API error: {resp.status}")
            data = await resp.json()
            image_url = data.get("data", [{}])[0].get("url")
            if not image_url:
                raise Exception("No image URL in response")
            async with session.get(image_url) as img_resp:
                return await img_resp.read()

async def masha_video_generate(prompt: str) -> str:
    """Заглушка для видео"""
    return "🎬 Генерация видео временно недоступна. Функция в разработке."

# ------------------------------------------------------------------
# Обработчики
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "🤖 *Привет! Я бот с поддержкой ИИ.*\n\n"
        "Я умею:\n"
        "✏️ генерировать текст (DeepSeek)\n"
        "🖼 создавать изображения (Nano Banana)\n"
        "🎬 генерировать видео (в разработке)\n\n"
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

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✏️ Генерация текста":
        await update.message.reply_text(
            "Введите ваш запрос. Я буду помнить контекст, пока вы не вернётесь в главное меню.",
            reply_markup=get_cancel_keyboard()
        )
        return TEXT_GEN
    elif text == "🖼 Генерация изображения":
        await update.message.reply_text(
            "Опишите, что нужно сгенерировать (изображение будет создано по модели Nano Banana):",
            reply_markup=get_cancel_keyboard()
        )
        return IMAGE_GEN
    elif text == "🎬 Генерация видео":
        await update.message.reply_text(
            "Опишите сценарий для видео (пока в разработке):",
            reply_markup=get_cancel_keyboard()
        )
        return VIDEO_GEN
    elif text == "🧹 Сбросить диалог":
        return await clear_dialog(update, context)
    else:
        # Если пользователь прислал текст вне меню, переходим в режим диалога
        return await start_dialog(update, context, text)

async def start_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str = None) -> int:
    user_id = update.effective_user.id
    if user_message is None:
        user_message = update.message.text

    save_message(user_id, "user", user_message)

    history = get_history(user_id, limit=10)

    try:
        await update.message.reply_chat_action("typing")
        answer = await deepseek_generate(user_message, history)
        await update.message.reply_text(answer, reply_markup=get_cancel_keyboard())
        save_message(user_id, "assistant", answer)
    except Exception as e:
        logger.exception("Ошибка генерации текста")
        await update.message.reply_text(
            "❌ Произошла ошибка при генерации. Попробуйте позже.",
            reply_markup=get_cancel_keyboard()
        )
    return DIALOG

async def handle_text_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        return await cancel(update, context)
    return await start_dialog(update, context, update.message.text)

async def handle_image_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        return await cancel(update, context)

    prompt = update.message.text
    user_id = update.effective_user.id
    await update.message.reply_chat_action("upload_photo")
    try:
        img_bytes = await masha_image_generate(prompt)
        await update.message.reply_photo(
            photo=io.BytesIO(img_bytes),
            caption=f"🖼 Ваше изображение по запросу:\n{prompt}",
            reply_markup=get_main_keyboard()
        )
        save_message(user_id, "user", f"Создай изображение: {prompt}")
        save_message(user_id, "assistant", "Изображение сгенерировано")
    except Exception as e:
        logger.exception("Ошибка генерации изображения")
        await update.message.reply_text(
            "❌ Не удалось создать изображение. Попробуйте другой запрос.",
            reply_markup=get_main_keyboard()
        )
    return MAIN_MENU

async def handle_video_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        return await cancel(update, context)

    prompt = update.message.text
    await update.message.reply_chat_action("typing")
    try:
        result = await masha_video_generate(prompt)
        await update.message.reply_text(
            result,
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.exception("Ошибка генерации видео")
        await update.message.reply_text(
            "❌ Функция видео временно недоступна.",
            reply_markup=get_main_keyboard()
        )
    return MAIN_MENU

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await start_dialog(update, context)

# ------------------------------------------------------------------
# Запуск
# ------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY не задан")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            TEXT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_gen)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_gen)],
            VIDEO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_video_gen)],
            DIALOG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_gen)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text("Используйте меню.")))

    logger.info("Бот запущен (текст: DeepSeek, изображения: Masha)")
    app.run_polling()

if __name__ == "__main__":
    main()
