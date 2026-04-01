import asyncio
import io
import logging
from typing import List, Tuple

import aiohttp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

from config import TELEGRAM_TOKEN, MASHA_API_KEY
from database import (
    init_db, save_message, get_history, clear_history, update_user_activity
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------- Константы -------------------
MASHA_BASE_URL = "https://api.mashagpt.ru/v1"  # фиксированный правильный URL

MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, DIALOG = range(5)

# ------------------- Клавиатуры -------------------
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

# ------------------- Вспомогательные функции -------------------
async def send_long_message(update: Update, text: str):
    """Разбивает длинный текст на части и отправляет"""
    if not text:
        return
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i+4096])

async def create_task(model: str, payload: dict, retries=3):
    """Создаёт задачу в MashaGPT (для изображений/видео)"""
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
async def masha_text_generate(prompt: str, history: List[Tuple[str, str]]) -> str:
    """Генерация текста через Masha (модель gpt-5-nano)"""
    messages = []
    for role, content in history[-5:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    url = f"{MASHA_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": MASHA_API_KEY
    }
    payload = {
        "model": "gpt-5-nano",
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.7
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"Masha API error {resp.status}: {error_text}")
                raise Exception(f"Masha error: {resp.status}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

async def masha_image_generate(prompt: str) -> bytes:
    """Генерация изображения через Masha (nano-banana-2)"""
    model = "nano-banana-2"
    payload = {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"}
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
        async with session.get(media_url) as img_resp:
            return await img_resp.read()

async def masha_video_generate(prompt: str) -> str:
    """Генерация видео через Masha (kling-2-6-text-to-video)"""
    model = "kling-2-6-text-to-video"
    payload = {"prompt": prompt, "aspectRatio": "16:9", "duration": "5", "sound": False}
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
    return media_url

# ------------------- Обработчики -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    init_db()
    user_id = update.effective_user.id
    update_user_activity(user_id)
    await update.message.reply_text(
        "🤖 *Привет! Я бот с поддержкой ИИ (MashaGPT).*\n\n"
        "Я умею:\n"
        "✏️ генерировать текст (GPT-5-nano)\n"
        "🖼 создавать изображения (Nano Banana 2)\n"
        "🎬 генерировать видео (Kling 2.6)\n\n"
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
            "Опишите, что нужно сгенерировать (изображение будет создано по модели Nano Banana 2):",
            reply_markup=get_cancel_keyboard()
        )
        return IMAGE_GEN
    elif text == "🎬 Генерация видео":
        await update.message.reply_text(
            "Опишите сценарий для видео (Kling 2.6, 5 секунд):",
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
        answer = await masha_text_generate(user_message, history)
        await send_long_message(update, answer)
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
            "❌ Не удалось создать изображение. Проверьте API-ключ MashaGPT или попробуйте другой запрос.",
            reply_markup=get_main_keyboard()
        )
    return MAIN_MENU

async def handle_video_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        return await cancel(update, context)

    prompt = update.message.text
    await update.message.reply_chat_action("upload_video")
    try:
        video_url = await masha_video_generate(prompt)
        # Отправляем ссылку на видео (Telegram не принимает видео по ссылке, только файл)
        # Поэтому лучше скачать и отправить файлом.
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as resp:
                video_bytes = await resp.read()
        await update.message.reply_video(
            video=io.BytesIO(video_bytes),
            caption=f"🎬 Видео по запросу:\n{prompt}",
            reply_markup=get_main_keyboard()
        )
        save_message(update.effective_user.id, "user", f"Создай видео: {prompt}")
        save_message(update.effective_user.id, "assistant", "Видео сгенерировано")
    except Exception as e:
        logger.exception("Ошибка генерации видео")
        await update.message.reply_text(
            "❌ Функция видео временно недоступна или произошла ошибка.",
            reply_markup=get_main_keyboard()
        )
    return MAIN_MENU

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await start_dialog(update, context)

# ------------------- Запуск -------------------
def main():
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

    logger.info("Бот запущен (текст, изображения и видео через Masha)")
    app.run_polling()

if __name__ == "__main__":
    main()
