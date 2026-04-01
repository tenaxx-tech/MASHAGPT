import asyncio
import io
import json
import logging
import os
import time
import sqlite3
from typing import Optional
import requests
import aiohttp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, PreCheckoutQueryHandler
)
from PIL import Image

# Импорт наших модулей
from config import TELEGRAM_TOKEN, MASHA_API_KEY, MASHA_BASE_URL, DEEPSEEK_API_KEY
from database import (
    init_db, get_user_balance, add_balance, deduct_balance,
    save_generation, get_weekly_image_count, increment_weekly_image_count
)

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------- Состояния -------------------
CHOOSING_ACTION, AWAITING_TEXT_PROMPT, AWAITING_IMAGE_PROMPT = range(3)

# ------------------- Клавиатуры -------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Текст (бесплатно)")],
        [KeyboardButton("🖼 Изображения (бесплатно, 5/неделя)")],
        [KeyboardButton("💰 Мой баланс")],
        [KeyboardButton("⭐ Пополнить звёзды")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True, one_time_keyboard=True)

# ------------------- Вспомогательные функции для MashaGPT -------------------
async def create_task(model, payload, retries=3):
    url = f"{MASHA_BASE_URL}/tasks/{model}"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 429:
                        wait = 2 ** attempt
                        logger.warning(f"429 Too Many Requests, повтор через {wait} сек")
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

async def get_task_status(task_id):
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

async def wait_for_task(task_id, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
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
    logger.error(f"Таймаут задачи {task_id}")
    return None

async def generate_text(prompt, model="gpt-5-nano", retries=3):
    url = f"{MASHA_BASE_URL}/chat/completions"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.7,
    }
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 429:
                        wait = 2 ** (attempt + 1)
                        logger.warning(f"429 Too Many Requests, повтор через {wait} сек")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Ошибка генерации текста (попытка {attempt+1}): {e}")
            if attempt == retries - 1:
                return None
            await asyncio.sleep(2)
    return None

async def generate_image(prompt, model="nano-banana-2"):
    # Упрощённая версия для изображений
    payload = {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"}
    task_id = await create_task(model, payload)
    if not task_id:
        raise Exception("Ошибка создания задачи")
    result = await wait_for_task(task_id)
    if not result:
        raise Exception("Таймаут или ошибка")
    outputs = result.get("output", [])
    if not outputs:
        raise Exception("Нет output в ответе")
    media_url = outputs[0].get("url")
    if not media_url:
        raise Exception("Нет URL в ответе")
    async with aiohttp.ClientSession() as session:
        async with session.get(media_url) as resp:
            return await resp.read()

# ------------------- Обработчики -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    await update.message.reply_text(
        "🌟 Добро пожаловать в AI-бот!\n\n"
        "✏️ Текст (бесплатно, без лимита)\n"
        "🖼 Изображения (бесплатно, 5 в неделю)\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    return CHOOSING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Отменено. Возвращаюсь в главное меню.",
        reply_markup=get_main_keyboard()
    )
    return CHOOSING_ACTION

async def send_typing_indicator(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        while True:
            await context.bot.send_chat_action(chat_id=chat_id, action='typing')
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✏️ Текст (бесплатно)":
        await update.message.reply_text(
            "Введите текст для генерации (можно использовать любую из бесплатных моделей):",
            reply_markup=get_cancel_keyboard()
        )
        return AWAITING_TEXT_PROMPT
    elif text == "🖼 Изображения (бесплатно, 5/неделя)":
        await update.message.reply_text(
            "Введите описание изображения:",
            reply_markup=get_cancel_keyboard()
        )
        return AWAITING_IMAGE_PROMPT
    elif text == "💰 Мой баланс":
        user_id = update.effective_user.id
        bal = get_user_balance(user_id)
        img_used = get_weekly_image_count(user_id)
        await update.message.reply_text(
            f"💰 Ваш баланс (для платных услуг): {bal} токенов\n"
            f"🖼 Бесплатные изображения: {img_used}/5 использовано на этой неделе",
            reply_markup=get_main_keyboard()
        )
        return CHOOSING_ACTION
    elif text == "⭐ Пополнить звёзды":
        # Пока заглушка
        await update.message.reply_text(
            "Функция пополнения звёздами временно недоступна.",
            reply_markup=get_main_keyboard()
        )
        return CHOOSING_ACTION
    elif text == "❌ Отмена":
        return await cancel(update, context)
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите пункт из меню.",
            reply_markup=get_main_keyboard()
        )
        return CHOOSING_ACTION

async def handle_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "❌ Отмена":
        return await cancel(update, context)

    prompt = update.message.text
    user_id = update.effective_user.id

    chat_id = update.effective_chat.id
    typing_task = asyncio.create_task(send_typing_indicator(chat_id, context))

    try:
        result = await generate_text(prompt)
        typing_task.cancel()
        if result:
            if len(result) > 4000:
                for i in range(0, len(result), 4000):
                    await update.message.reply_text(result[i:i+4000])
            else:
                await update.message.reply_text(result)
            save_generation(user_id, "gpt-5-nano", prompt)
        else:
            await update.message.reply_text("❌ Ошибка генерации текста. Попробуйте позже.")
    except Exception as e:
        typing_task.cancel()
        logger.exception("Ошибка в handle_text_prompt")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return CHOOSING_ACTION

async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "❌ Отмена":
        return await cancel(update, context)

    prompt = update.message.text
    user_id = update.effective_user.id

    used = get_weekly_image_count(user_id)
    if used >= 5:
        await update.message.reply_text(
            "❌ Вы уже использовали все 5 бесплатных генераций изображений на этой неделе. Лимит обновится в понедельник.",
            reply_markup=get_main_keyboard()
        )
        return CHOOSING_ACTION

    chat_id = update.effective_chat.id
    typing_task = asyncio.create_task(send_typing_indicator(chat_id, context))

    try:
        img_bytes = await generate_image(prompt)
        typing_task.cancel()
        await update.message.reply_photo(photo=io.BytesIO(img_bytes), caption="🖼️ Результат")
        increment_weekly_image_count(user_id)
        save_generation(user_id, "nano-banana-2", prompt)
    except Exception as e:
        typing_task.cancel()
        logger.exception("Ошибка генерации изображения")
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return CHOOSING_ACTION

# ------------------- Платежи (заглушка) -------------------
async def buy_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Функция пополнения звёздами временно недоступна.")

async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=False, error_message="Платежи временно отключены")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

# ------------------- Запуск -------------------
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            AWAITING_TEXT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_prompt)],
            AWAITING_IMAGE_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_prompt)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('help', lambda u,c: u.message.reply_text("Используйте меню.")))
    # Платежи временно отключены
    # app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    # app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    logger.info("Telegram-бот запущен (только текст и изображения)")
    app.run_polling()

if __name__ == "__main__":
    main()