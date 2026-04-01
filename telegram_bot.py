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

from config import TELEGRAM_TOKEN, MASHA_API_KEY, MASHA_BASE_URL
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
# Вспомогательные функции для работы с Masha API
# ------------------------------------------------------------------
async def masha_text_generate(prompt: str, history: List[Tuple[str, str]]) -> str:
    """
    Вызов Masha API для генерации текста с учётом истории.
    history: список кортежей (role, content)
    """
    messages = []
    # Добавляем историю (до 5 последних сообщений, чтобы не перегружать контекст)
    for role, content in history[-5:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    url = f"{MASHA_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": MASHA_API_KEY
    }
    payload = {
        "model": "gpt-5-nano",   # бесплатная модель
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.7
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"Masha API error {resp.status}: {error_text}")
                raise Exception(f"API error: {resp.status}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

async def masha_image_generate(prompt: str) -> bytes:
    """Генерация изображения через Nano Banana"""
    # Предполагается, что у Masha есть эндпоинт для генерации изображений
    # Формат может отличаться, уточните в документации.
    # Ниже пример, адаптируйте под реальный API.
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
            # Допустим, API возвращает URL изображения
            image_url = data.get("data", [{}])[0].get("url")
            if not image_url:
                raise Exception("No image URL in response")
            # Скачиваем изображение
            async with session.get(image_url) as img_resp:
                return await img_resp.read()

async def masha_video_generate(prompt: str) -> str:
    """Заглушка для видео (Sora пока недоступна бесплатно)"""
    # Возвращаем сообщение-заглушку
    return "🎬 Генерация видео временно недоступна. Функция в разработке."

# ------------------------------------------------------------------
# Обработчики
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start – инициализация"""
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "🤖 *Привет! Я бот с поддержкой ИИ.*\n\n"
        "Я умею:\n"
        "✏️ генерировать текст\n"
        "🖼 создавать изображения\n"
        "🎬 генерировать видео (в разработке)\n\n"
        "*Я помню контекст диалога!* Просто отправляйте сообщения, и я буду отвечать, учитывая историю.\n"
        "Чтобы сменить режим или сбросить историю, используйте кнопки внизу.\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат в главное меню"""
    await update.message.reply_text(
        "🔙 Возвращаемся в главное меню.",
        reply_markup=get_main_keyboard()
    )
    return MAIN_MENU

async def clear_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сброс истории диалога"""
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
    """Начинаем диалог с учётом истории"""
    user_id = update.effective_user.id
    if user_message is None:
        user_message = update.message.text

    # Сохраняем сообщение пользователя
    save_message(user_id, "user", user_message)

    # Получаем историю
    history = get_history(user_id, limit=10)  # список кортежей (role, content)

    # Генерируем ответ
    try:
        await update.message.reply_chat_action("typing")
        answer = await masha_text_generate(user_message, history)
        await update.message.reply_text(answer, reply_markup=get_cancel_keyboard())
        # Сохраняем ответ ассистента
        save_message(user_id, "assistant", answer)
    except Exception as e:
        logger.exception("Ошибка генерации текста")
        await update.message.reply_text(
            "❌ Произошла ошибка при генерации. Попробуйте позже.",
            reply_markup=get_cancel_keyboard()
        )
    return DIALOG

async def handle_text_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода для текстовой генерации"""
    if update.message.text == "🔙 Главное меню":
        return await cancel(update, context)
    # Передаём в диалог
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
        # Сохраняем в историю (опционально)
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
    """Если пришло сообщение без состояния"""
    return await start_dialog(update, context)

# ------------------------------------------------------------------
# Запуск
# ------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            TEXT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_gen)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_gen)],
            VIDEO_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_video_gen)],
            DIALOG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_gen)],  # продолжение диалога
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text("Используйте меню.")))

    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
