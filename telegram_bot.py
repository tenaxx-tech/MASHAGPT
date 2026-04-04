import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import logging
import requests
import time
import os
import json
from urllib.parse import quote

from config import VK_TOKEN, MASHA_API_KEY, MASHA_BASE_URL
from database import (
    init_db, get_user_balance, add_balance, deduct_balance,
    set_current_model, get_current_model, save_generation
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== ЦЕНЫ МОДЕЛЕЙ (в токенах) ==========
MODEL_PRICES = {
    # Текст
    "gpt-5-nano": 0.5,
    "gpt-5-mini": 0.25,
    "gpt-4o-mini": 0.15,
    "deepseek-chat": 0.7,
    # Изображения
    "nano-banana-2": 5,
    "flux-2": 7,
    "midjourney": 8,
    "grok-imagine-text-to-image": 2,
    "gpt-image-1-5-text-to-image": 3,
    # Видео
    "kling-2-6-text-to-video": 55,
    "wan-2-6-text-to-video": 60,
    "sora-2-text-to-video": 45,
    # Обработка изображений
    "recraft-remove-background": 3,
    "recraft-crisp-upscale": 2,
    "topaz-image-upscale": 4,
    "codeplugtech-face-swap": 1.3,
    "qwen-edit-multiangle": 15,
    # Аудио (песни)
    "elevenlabs-tts-multilingual-v2": 1,
}

# ========== КАТЕГОРИИ И МОДЕЛИ ==========
CATEGORIES = {
    "text": {"name": "✏️ Текст", "models": [
        ("gpt-5-nano", "GPT-5 nano", 0.5),
        ("gpt-5-mini", "GPT-5 mini", 0.25),
        ("gpt-4o-mini", "GPT-4o mini", 0.15),
        ("deepseek-chat", "DeepSeek Chat", 0.7)
    ]},
    "image": {"name": "🖼 Изображения", "models": [
        ("nano-banana-2", "Nano Banana 2", 5),
        ("flux-2", "Flux 2", 7),
        ("midjourney", "Midjourney", 8),
        ("grok-imagine-text-to-image", "Grok Imagine", 2),
        ("gpt-image-1-5-text-to-image", "GPT Image 1.5", 3)
    ]},
    "video": {"name": "🎬 Видео", "models": [
        ("kling-2-6-text-to-video", "Kling 2.6", 55),
        ("wan-2-6-text-to-video", "Wan 2.6", 60),
        ("sora-2-text-to-video", "Sora 2", 45)
    ]},
    "edit": {"name": "✨ Обработка", "models": [
        ("recraft-remove-background", "Удаление фона", 3),
        ("recraft-crisp-upscale", "Увеличение (4x)", 2),
        ("topaz-image-upscale", "Апскейл (8x)", 4),
        ("codeplugtech-face-swap", "Замена лица", 1.3),
        ("qwen-edit-multiangle", "Мультиракурс", 15)
    ]},
    "audio": {"name": "🎵 Музыка", "models": [
        ("elevenlabs-tts-multilingual-v2", "Генерация песни", 1)
    ]}
}

# ========== ХРАНИЛИЩЕ СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЕЙ ==========
user_state = {}

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ MASHAGPT ==========
def create_task(model, payload, retries=3):
    url = f"{MASHA_BASE_URL}/tasks/{model}"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"429 Too Many Requests, повтор через {wait} сек (попытка {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("id")
        except Exception as e:
            logger.error(f"Ошибка создания задачи {model} (попытка {attempt+1}): {e}")
            if attempt == retries - 1:
                return None
            time.sleep(2)
    return None

def get_task_status(task_id):
    url = f"{MASHA_BASE_URL}/tasks/{task_id}"
    headers = {"x-api-key": MASHA_API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка получения статуса {task_id}: {e}")
        return None

def wait_for_task(task_id, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        data = get_task_status(task_id)
        if not data:
            return None
        # Если data не словарь, а строка (например, ошибка), то возвращаем None
        if not isinstance(data, dict):
            logger.error(f"Неверный формат ответа: {data}")
            return None
        status = data.get("status")
        if status == "COMPLETED":
            return data
        elif status == "FAILED":
            logger.error(f"Задача {task_id} провалилась: {data.get('errorMessage')}")
            return None
        time.sleep(2)
    logger.error(f"Таймаут задачи {task_id}")
    return None

def generate_text(prompt, model="gpt-5-nano", retries=3):
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
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"429 Too Many Requests, повтор через {wait} сек (попытка {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка генерации текста (попытка {attempt+1}): {e}")
            if attempt == retries - 1:
                return None
            time.sleep(2)
    return None

def generate_audio(prompt, model="elevenlabs-tts-multilingual-v2"):
    payload = {
        "text": prompt,
        "voice": "Rachel",
        "stability": 0.5,
        "similarityBoost": 0.75,
        "speed": 1.0,
        "languageCode": "ru"
    }
    task_id = create_task(model, payload)
    if not task_id:
        return None
    result = wait_for_task(task_id)
    if result and isinstance(result, dict) and result.get("output"):
        return result["output"][0].get("url")
    return None

def build_payload(model, prompt, image_url=None):
    if model == "nano-banana-2":
        return {"prompt": prompt, "aspectRatio": "1:1", "resolution": "1K"}
    elif model == "flux-2":
        return {"prompt": prompt, "model": "pro", "aspectRatio": "1:1", "resolution": "1K"}
    elif model == "midjourney":
        return {"taskType": "mj_txt2img", "prompt": prompt, "aspectRatio": "1:1", "speed": "fast"}
    elif model == "grok-imagine-text-to-image":
        return {"prompt": prompt, "aspectRatio": "1:1"}
    elif model == "gpt-image-1-5-text-to-image":
        return {"prompt": prompt, "aspectRatio": "1:1", "quality": "medium"}
    elif model == "kling-2-6-text-to-video":
        return {"prompt": prompt, "aspectRatio": "16:9", "duration": "5", "sound": False}
    elif model == "wan-2-6-text-to-video":
        return {"prompt": prompt, "duration": "5", "resolution": "720p"}
    elif model == "sora-2-text-to-video":
        return {"prompt": prompt, "aspectRatio": "landscape", "duration": "10", "removeWatermark": True}
    elif model == "recraft-remove-background":
        return {"imageUrl": image_url} if image_url else None
    elif model == "recraft-crisp-upscale":
        return {"imageUrl": image_url} if image_url else None
    elif model == "topaz-image-upscale":
        return {"imageUrl": image_url, "upscaleFactor": "2"} if image_url else None
    elif model == "codeplugtech-face-swap":
        if image_url and " " in image_url:
            urls = image_url.split()
            return {"inputImage": urls[0], "swapImage": urls[1]}
        else:
            return None
    elif model == "qwen-edit-multiangle":
        return {"prompt": prompt, "image": image_url} if image_url else {"prompt": prompt, "image": None}
    elif model == "elevenlabs-tts-multilingual-v2":
        return {"text": prompt, "voice": "Rachel", "stability": 0.5, "similarityBoost": 0.75, "speed": 1.0, "languageCode": "ru"}
    else:
        return None

# ========== ФУНКЦИИ VK ==========
def send_message(vk, user_id, message, keyboard=None):
    params = {'user_id': user_id, 'message': message, 'random_id': 0}
    if keyboard:
        params['keyboard'] = keyboard.get_keyboard()
    vk.messages.send(**params)

def upload_photo(vk, photo_url, peer_id):
    try:
        response = requests.get(photo_url, timeout=30)
        response.raise_for_status()
        temp_file = f"/tmp/vk_photo_{int(time.time())}.jpg"
        with open(temp_file, "wb") as f:
            f.write(response.content)

        upload_server = vk.photos.getMessagesUploadServer(peer_id=peer_id)
        upload_url = upload_server['upload_url']
        with open(temp_file, "rb") as f:
            upload_response = requests.post(upload_url, files={'photo': f})
        upload_data = upload_response.json()

        photo = vk.photos.saveMessagesPhoto(**upload_data)[0]
        os.remove(temp_file)
        return f"photo{photo['owner_id']}_{photo['id']}"
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {e}")
        return None

def get_photo_url_from_attachment(vk, attachment):
    # attachment должен быть словарём
    if not isinstance(attachment, dict):
        logger.warning(f"Attachment не словарь: {attachment}")
        return None
    if attachment.get('type') == 'photo':
        photo = attachment.get('photo')
        if not isinstance(photo, dict):
            return None
        sizes = photo.get('sizes', [])
        if sizes:
            # сортируем по площади
            sizes.sort(key=lambda x: x.get('width', 0) * x.get('height', 0))
            return sizes[-1].get('url')
    return None

def send_text(vk, user_id, text):
    while len(text) > 4096:
        part = text[:4096]
        send_message(vk, user_id, part)
        text = text[4096:]
    send_message(vk, user_id, text)

def show_cabinet(vk, user_id):
    bal = get_user_balance(user_id)
    metadata = json.dumps({"user_id": user_id})
    encoded_metadata = quote(metadata)
    pay_link = f"https://www.donationalerts.com/r/designdmitriy?metadata={encoded_metadata}"

    text = (
        f"👤 Личный кабинет\n\n"
        f"💰 Баланс: {bal} токенов\n\n"
        f"1 токен = 1 рубль\n\n"
        f"🔗 Ссылка для пополнения:\n{pay_link}\n\n"
        f"💡 После оплаты токены начислятся автоматически."
    )
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_openlink_button("💳 Пополнить", link=pay_link)
    keyboard.add_button("🔙 Назад", color=VkKeyboardColor.NEGATIVE)
    send_message(vk, user_id, text, keyboard=keyboard)

def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("✏️ Текст", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("🖼 Изображения", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("🎬 Видео", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("🎵 Музыка", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("✨ Обработка", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("👤 Личный кабинет", color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_category_keyboard(category):
    keyboard = VkKeyboard(one_time=False)
    models = CATEGORIES[category]["models"]
    if category == "edit":
        row = []
        for i, (model_id, label, price) in enumerate(models):
            row.append(f"{label} ({price} т.)")
            if len(row) == 3 or i == len(models)-1:
                for btn in row:
                    keyboard.add_button(btn, color=VkKeyboardColor.SECONDARY)
                keyboard.add_line()
                row = []
    else:
        for model_id, label, price in models:
            keyboard.add_button(f"{label} ({price} т.)", color=VkKeyboardColor.SECONDARY)
        keyboard.add_line()
    keyboard.add_button("🔙 Назад", color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_model_keyboard(model_id):
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("✨ Сгенерировать", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("🔙 Назад к моделям", color=VkKeyboardColor.NEGATIVE)
    return keyboard

# ========== ОСНОВНОЙ ОБРАБОТЧИК ==========
def handle_message(vk, event):
    user_id = event.user_id
    text = event.text.lower().strip() if event.text else ""

    if not text:
        return

    if user_id not in user_state:
        user_state[user_id] = {"stage": "main", "model": None}

    stage = user_state[user_id]["stage"]

    # ========== КНОПКИ ГЛАВНОГО МЕНЮ ==========
    if text == "✏️ текст":
        user_state[user_id]["stage"] = "category"
        user_state[user_id]["category"] = "text"
        send_message(vk, user_id, "Выбери модель для генерации текста:", keyboard=get_category_keyboard("text"))
        return
    elif text == "🖼 изображения":
        user_state[user_id]["stage"] = "category"
        user_state[user_id]["category"] = "image"
        send_message(vk, user_id, "Выбери модель для генерации изображения:", keyboard=get_category_keyboard("image"))
        return
    elif text == "🎬 видео":
        user_state[user_id]["stage"] = "category"
        user_state[user_id]["category"] = "video"
        send_message(vk, user_id, "Выбери модель для генерации видео:", keyboard=get_category_keyboard("video"))
        return
    elif text == "🎵 музыка":
        user_state[user_id]["stage"] = "category"
        user_state[user_id]["category"] = "audio"
        send_message(vk, user_id, "Выбери модель для генерации музыки:", keyboard=get_category_keyboard("audio"))
        return
    elif text == "✨ обработка":
        user_state[user_id]["stage"] = "category"
        user_state[user_id]["category"] = "edit"
        send_message(vk, user_id, "Выбери модель для обработки изображений:", keyboard=get_category_keyboard("edit"))
        return
    elif text == "👤 личный кабинет":
        show_cabinet(vk, user_id)
        return
    elif text == "🔙 назад":
        user_state[user_id]["stage"] = "main"
        user_state[user_id]["model"] = None
        send_message(vk, user_id, "Главное меню:", keyboard=get_main_keyboard())
        return

    # ========== ВЫБОР МОДЕЛИ В КАТЕГОРИИ ==========
    if stage == "category":
        category = user_state[user_id]["category"]
        for model_id, label, price in CATEGORIES[category]["models"]:
            if text == f"{label} ({price} т.)".lower():
                user_state[user_id]["model"] = model_id
                # Для моделей обработки (требуют изображение)
                if model_id in ["recraft-remove-background", "recraft-crisp-upscale", "topaz-image-upscale",
                                "codeplugtech-face-swap", "qwen-edit-multiangle"]:
                    user_state[user_id]["stage"] = "await_image"
                    send_message(vk, user_id, f"Модель: {label}\nСтоимость: {price} токенов\n\nОтправьте изображение (фото), которое нужно обработать.")
                else:
                    user_state[user_id]["stage"] = "model"
                    send_message(vk, user_id,
                                 f"Модель: {label}\nСтоимость: {price} токенов\nНажми «Сгенерировать», чтобы начать:",
                                 keyboard=get_model_keyboard(model_id))
                return
        send_message(vk, user_id, "Пожалуйста, выбери модель из списка.")
        return

    # ========== НАЖАТИЕ "СГЕНЕРИРОВАТЬ" ==========
    if stage == "model" and text == "✨ сгенерировать":
        user_state[user_id]["stage"] = "await_prompt"
        send_message(vk, user_id, "Отправь текстовое описание (промпт) для генерации:")
        return

    # ========== ОБРАБОТКА ПРОМПТА (ТЕКСТ/АУДИО/ИЗОБРАЖЕНИЯ/ВИДЕО) ==========
    if stage == "await_prompt":
        model = user_state[user_id]["model"]
        cost = MODEL_PRICES.get(model, 0)
        if get_user_balance(user_id) < cost:
            send_message(vk, user_id,
                         f"❌ Недостаточно токенов. Нужно: {cost}, у вас: {get_user_balance(user_id)}. Пополните баланс.",
                         keyboard=get_main_keyboard())
            user_state[user_id]["stage"] = "main"
            return

        send_message(vk, user_id, "⏳ Генерирую...")

        if not deduct_balance(user_id, cost):
            send_message(vk, user_id, "Ошибка списания токенов.")
            user_state[user_id]["stage"] = "main"
            return

        # Генерация текста
        if model.startswith("gpt") or model == "deepseek-chat":
            result = generate_text(event.text, model=model)
            if result:
                send_text(vk, user_id, result)
                save_generation(user_id, model, event.text)
            else:
                send_message(vk, user_id, "❌ Ошибка генерации текста.")
                add_balance(user_id, cost)

        # Генерация аудио (песня)
        elif model == "elevenlabs-tts-multilingual-v2":
            audio_url = generate_audio(event.text, model=model)
            if audio_url:
                send_message(vk, user_id, f"🎵 Аудио: {audio_url}")
                save_generation(user_id, model, event.text)
            else:
                send_message(vk, user_id, "❌ Ошибка генерации аудио.")
                add_balance(user_id, cost)

        # Генерация изображений / видео
        else:
            payload = build_payload(model, event.text)
            if not payload:
                send_message(vk, user_id, "❌ Не удалось сформировать запрос.")
                add_balance(user_id, cost)
                user_state[user_id]["stage"] = "main"
                return

            task_id = create_task(model, payload)
            time.sleep(2)  # небольшая задержка для разгрузки API
            if not task_id:
                send_message(vk, user_id, "❌ Ошибка создания задачи.")
                add_balance(user_id, cost)
                user_state[user_id]["stage"] = "main"
                return

            result_data = wait_for_task(task_id)
            if not result_data:
                send_message(vk, user_id, "⚠️ Таймаут или ошибка.")
                add_balance(user_id, cost)
                user_state[user_id]["stage"] = "main"
                return

            outputs = result_data.get("output", [])
            if outputs:
                media_url = outputs[0].get("url")
                if media_url:
                    if "image" in model or "face-swap" in model or "upscale" in model or "remove-background" in model:
                        attachment = upload_photo(vk, media_url, user_id)
                        if attachment:
                            send_message(vk, user_id, "✅ Результат:", keyboard=None)
                            vk.messages.send(user_id=user_id, attachment=attachment, random_id=0)
                        else:
                            send_message(vk, user_id, f"✅ Результат: {media_url}")
                    elif "video" in model:
                        send_message(vk, user_id, f"🎬 Видео: {media_url}")
                    else:
                        send_message(vk, user_id, f"Результат: {media_url}")
                    save_generation(user_id, model, event.text)
                else:
                    send_message(vk, user_id, "❌ Нет URL в ответе.")
            else:
                send_message(vk, user_id, "❌ Не удалось получить контент.")
                add_balance(user_id, cost)

        user_state[user_id]["stage"] = "main"
        send_message(vk, user_id, "Что дальше?", keyboard=get_main_keyboard())
        return

    # ========== ОБРАБОТКА ИЗОБРАЖЕНИЙ (ДЛЯ МОДЕЛЕЙ ОБРАБОТКИ) ==========
    if stage == "await_image":
        if event.attachments:
            photo_url = None
            for attachment in event.attachments:
                if isinstance(attachment, dict) and attachment.get('type') == 'photo':
                    photo_url = get_photo_url_from_attachment(vk, attachment)
                    break
            if not photo_url:
                send_message(vk, user_id, "Пожалуйста, отправьте изображение (фото).")
                return

            model = user_state[user_id]["model"]
            cost = MODEL_PRICES.get(model, 0)
            if get_user_balance(user_id) < cost:
                send_message(vk, user_id,
                             f"❌ Недостаточно токенов. Нужно: {cost}, у вас: {get_user_balance(user_id)}. Пополните баланс.",
                             keyboard=get_main_keyboard())
                user_state[user_id]["stage"] = "main"
                return

            send_message(vk, user_id, "⏳ Обрабатываю изображение...")

            if not deduct_balance(user_id, cost):
                send_message(vk, user_id, "Ошибка списания токенов.")
                user_state[user_id]["stage"] = "main"
                return

            # Для моделей обработки передаём URL фото (без текстового промпта)
            payload = build_payload(model, None, image_url=photo_url)
            if not payload:
                send_message(vk, user_id, "❌ Не удалось сформировать запрос.")
                add_balance(user_id, cost)
                user_state[user_id]["stage"] = "main"
                return

            task_id = create_task(model, payload)
            time.sleep(2)
            if not task_id:
                send_message(vk, user_id, "❌ Ошибка создания задачи.")
                add_balance(user_id, cost)
                user_state[user_id]["stage"] = "main"
                return

            result_data = wait_for_task(task_id)
            if not result_data:
                send_message(vk, user_id, "⚠️ Таймаут или ошибка.")
                add_balance(user_id, cost)
                user_state[user_id]["stage"] = "main"
                return

            outputs = result_data.get("output", [])
            if outputs:
                media_url = outputs[0].get("url")
                if media_url:
                    attachment = upload_photo(vk, media_url, user_id)
                    if attachment:
                        send_message(vk, user_id, "✅ Результат:", keyboard=None)
                        vk.messages.send(user_id=user_id, attachment=attachment, random_id=0)
                    else:
                        send_message(vk, user_id, f"✅ Результат: {media_url}")
                    save_generation(user_id, model, f"обработка фото {photo_url}")
                else:
                    send_message(vk, user_id, "❌ Нет URL в ответе.")
            else:
                send_message(vk, user_id, "❌ Не удалось получить контент.")
                add_balance(user_id, cost)

            user_state[user_id]["stage"] = "main"
            send_message(vk, user_id, "Что дальше?", keyboard=get_main_keyboard())
            return
        else:
            send_message(vk, user_id, "Пожалуйста, отправьте изображение (фото).")
            return

    # ========== ЕСЛИ НИЧЕГО НЕ ПОДОШЛО ==========
    send_message(vk, user_id, "Главное меню:", keyboard=get_main_keyboard())

# ========== ЗАПУСК ==========
def main():
    init_db()
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkLongPoll(vk_session)

    logger.info("Бот ВКонтакте запущен")
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            try:
                handle_message(vk, event)
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}")
                send_message(vk, event.user_id, "Произошла ошибка, попробуйте позже.")

if __name__ == "__main__":
    main()
