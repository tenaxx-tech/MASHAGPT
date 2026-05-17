# ------------------- ОБРАБОТЧИКИ -------------------
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
        f"💎 **Платное изображение:** {PAID_IMAGE_PRICE} промтов\n\n"
        f"📞 [Написать создателю](https://t.me/Dmitriy_Uretskiy)"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Пополнить (Stars)", callback_data="topup")],
        [InlineKeyboardButton("💳 Робокасса", callback_data="robokassa_topup")],
        [InlineKeyboardButton("📞 Поддержка", url="https://t.me/Dmitriy_Uretskiy")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
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
            "Сначала я сгенерирую фон (изображение без текста) на основе ваших пожеланий, "
            "а затем вы сможете добавить текст (название, преимущества, товары/услуги).\n\n"
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

    elif text == "🖼 9. Изменить размер изображения":
        context.user_data.clear()
        await update.message.reply_text(
            "🖼 *Изменить размер изображения*\n\n"
            "Отправьте изображение, размер которого нужно изменить.\n"
            "Затем укажите новый размер в формате ШиринаxВысота (например, 1024x1024 или 1920x1080).",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return AWAIT_RESIZE_IMAGE

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

# ------------------- ОБРАБОТЧИК ИЗМЕНЕНИЯ РАЗМЕРА (исправлен) -------------------
async def handle_resize_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.", reply_markup=get_cancel_keyboard())
        return AWAIT_RESIZE_IMAGE
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['resize_image_url'] = photo_file.file_path
    await update.message.reply_text(
        "✅ Изображение получено.\n\n"
        "Теперь введите желаемый размер в формате ШиринаxВысота (например, 1024x1024, 1920x1080).\n"
        "Пресеты: 1:1 → 1024x1024, 16:9 → 1920x1080, 9:16 → 1080x1920",
        reply_markup=get_cancel_keyboard()
    )
    return AWAIT_RESIZE_SIZE

async def handle_resize_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    size_input = update.message.text.strip().lower()
    if size_input == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    preset_map = {"1:1": "1024x1024", "квадрат": "1024x1024", "16:9": "1920x1080", "1920x1080": "1920x1080", "9:16": "1080x1920", "1080x1920": "1080x1920"}
    if size_input in preset_map:
        size = preset_map[size_input]
    else:
        if 'x' not in size_input:
            await update.message.reply_text("❌ Неверный формат. Используйте ШиринаxВысота.", reply_markup=get_cancel_keyboard())
            return AWAIT_RESIZE_SIZE
        parts = size_input.split('x')
        if len(parts) != 2:
            await update.message.reply_text("❌ Неверный формат.", reply_markup=get_cancel_keyboard())
            return AWAIT_RESIZE_SIZE
        try:
            w, h = int(parts[0]), int(parts[1])
            if w <= 0 or h <= 0:
                raise ValueError
            size = f"{w}x{h}"
        except:
            await update.message.reply_text("❌ Ширина и высота должны быть положительными числами.", reply_markup=get_cancel_keyboard())
            return AWAIT_RESIZE_SIZE

    image_url = context.user_data.get('resize_image_url')
    if not image_url:
        await update.message.reply_text("Ошибка: изображение не найдено.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Стоимость операции (можно настроить)
    price = 2
    if get_user_balance(user_id) < price:
        await update.message.reply_text(f"❌ Недостаточно промтов. Нужно {price}.", reply_markup=get_main_keyboard())
        return MAIN_MENU
    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    await update.message.reply_text(f"🖼 Изменяю размер до {size}. Пожалуйста, подождите...")

    # ИСПРАВЛЕНИЕ: Используем модель flux-2 (или nano-banana-2, midjourney) для изменения размера
    # Вы можете заменить на любую другую рабочую модель из списка
    model = "flux-2"  # работающая модель для изменения размера
    # Изменяем размер с помощью модели flux-2
    # Получаем оригинальное изображение и отправляем на генерацию с указанием нового размера
    prompt = f"Измени размер этого изображения ровно до {size}. Сохрани содержимое без искажений."
    payload = {
        "prompt": prompt,
        "size": size,
        "n": 1,
        "response_format": "url"
    }
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
        if result_bytes:
            compressed = await compress_image(result_bytes)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption=f"🖼 Изображение изменено до {size}")
            await update.message.reply_text(f"📥 Оригинал: {media_url}")
            save_message(user_id, "user", f"resize image to {size}")
            save_message(user_id, "assistant", "Изображение изменено")
        else:
            await update.message.reply_text("❌ Не удалось изменить размер.")
            add_balance(user_id, price)
    except Exception as e:
        logger.exception("Ошибка изменения размера")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ -------------------
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

# ------------------- ОЖИВЛЕНИЕ ФОТО (Wan 2.6) -------------------
async def handle_animate_photo_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    model = "wan-2-6-image-to-video"
    price = 3

    balance = get_user_balance(user_id)
    if balance < price:
        await update.message.reply_text(
            f"❌ Недостаточно промтов для оживления фото. Нужно: {price}, у вас: {balance}.\n"
            "Пополните баланс через кнопку «💰 Мой баланс».",
            reply_markup=get_main_keyboard()
        )
        return MAIN_MENU

    if not deduct_balance(user_id, price):
        await update.message.reply_text("❌ Ошибка списания промтов.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    prompt = None
    if text.lower() != "пропустить" and text:
        prompt = text

    payload = build_payload(model, prompt=prompt, image_url=photo_url)
    if not payload:
        await update.message.reply_text("❌ Не удалось сформировать запрос для Wan 2.6.", reply_markup=get_main_keyboard())
        add_balance(user_id, price)
        return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.UPLOAD_VIDEO, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка оживления фото (Wan 2.6)")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        add_balance(user_id, price)
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
        add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_popular_menu_keyboard())
    return POPULAR_MENU

# ------------------- ОБРАБОТЧИКИ ДЛЯ ОДНОКРАТНЫХ ИЗОБРАЖЕНИЙ (удаление фона, улучшение) -------------------
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

# ------------------- ОБРАБОТЧИКИ ДЛЯ FACE SWAP -------------------
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

# ------------------- ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ ИЗОБРАЖЕНИЯ (img2img) -------------------
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

# ------------------- ОБРАБОТЧИКИ АВАТАРА (говорящая голова) -------------------
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

# ------------------- ОБРАБОТЧИКИ АНИМАЦИИ ПЕРСОНАЖА -------------------
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

# ------------------- УПАКОВКА ГРУППЫ ВК -------------------
def wrap_text(text: str, font, max_width: int, draw: ImageDraw.Draw) -> List[str]:
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    if current_line:
        lines.append(' '.join(current_line))
    return lines

def add_text_to_image(image_bytes: bytes, text_data: dict, target_size: tuple = None) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        if target_size:
            img = img.resize(target_size, Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(img)
        width, height = img.size
        try:
            base_font_size = max(20, min(width, height) // 25)
            font = ImageFont.truetype(FONT_PATH, base_font_size)
            font_small = ImageFont.truetype(FONT_PATH, base_font_size - 4)
            font_large = ImageFont.truetype(FONT_PATH, base_font_size + 8)
        except:
            font = font_small = font_large = ImageFont.load_default()
        def get_font_height(f):
            ascent, descent = f.getmetrics()
            return ascent + descent
        font_height_large = get_font_height(font_large)
        font_height_small = get_font_height(font_small)
        text_color = (255, 255, 255)
        shadow_color = (0, 0, 0)
        top_margin = height // 5
        left_margin = width // 20
        right_margin = width // 20
        max_text_width = width - left_margin - right_margin
        title = text_data.get('title', 'Название').upper()
        advantages = text_data.get('advantages', '').upper()
        adv_list = [a.strip() for a in advantages.split(',') if a.strip()]
        products = text_data.get('products', '').upper()
        services = text_data.get('services', '').upper()
        prod_list = [p.strip() for p in products.split(',') if p.strip()]
        serv_list = [s.strip() for s in services.split(',') if s.strip()]
        y = top_margin + 10
        title_lines = wrap_text(title, font_large, max_text_width // 2, draw)
        for line in title_lines:
            draw.text((left_margin, y), line, font=font_large, fill=text_color, stroke_width=1, stroke_fill=shadow_color)
            y += font_height_large + 5
        y += 15
        for adv in adv_list[:4]:
            adv_lines = wrap_text(adv, font_small, max_text_width // 2, draw)
            for line in adv_lines:
                draw.text((left_margin, y), line, font=font_small, fill=text_color, stroke_width=1, stroke_fill=shadow_color)
                y += font_height_small + 3
            y += 5
        x_right = width - max_text_width // 2 - right_margin
        y_right = top_margin + 10
        if prod_list:
            draw.text((x_right, y_right), "ТОВАРЫ", font=font_large, fill=text_color, stroke_width=1, stroke_fill=shadow_color)
            y_right += font_height_large + 10
            for prod in prod_list[:6]:
                prod_lines = wrap_text(prod, font_small, max_text_width // 2, draw)
                for line in prod_lines:
                    draw.text((x_right, y_right), f"• {line}", font=font_small, fill=text_color, stroke_width=1, stroke_fill=shadow_color)
                    y_right += font_height_small + 3
                y_right += 5
        y_right += 15
        if serv_list:
            draw.text((x_right, y_right), "УСЛУГИ", font=font_large, fill=text_color, stroke_width=1, stroke_fill=shadow_color)
            y_right += font_height_large + 10
            for serv in serv_list[:6]:
                serv_lines = wrap_text(serv, font_small, max_text_width // 2, draw)
                for line in serv_lines:
                    draw.text((x_right, y_right), f"✓ {line}", font=font_small, fill=text_color, stroke_width=1, stroke_fill=shadow_color)
                    y_right += font_height_small + 3
                y_right += 5
        output = io.BytesIO()
        img.save(output, format='PNG')
        return output.getvalue()

async def generate_background_image(prompt: str, target_w: int, target_h: int):
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
        logger.exception(f"Ошибка генерации фона: {e}")
        return None, None

async def generate_multiple_backgrounds(update, context, prompt, w, h, elem_type):
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
    backgrounds = []
    for i in range(1, 4):
        await update.message.reply_text(f"🖼 Генерирую фон для виджета {i}...")
        img_bytes, url = await generate_background_image(prompt, w, h)
        if img_bytes:
            backgrounds.append(img_bytes)
        else:
            await update.message.reply_text(f"❌ Не удалось сгенерировать виджет {i}.")
            if paid:
                add_balance(user_id, PAID_IMAGE_PRICE)
            return MAIN_MENU
    if not paid and used < 5:
        increment_weekly_image_count(user_id)
    context.user_data['vk_backgrounds'] = backgrounds
    context.user_data['vk_elem_type'] = "виджеты"
    context.user_data['vk_width'] = w
    context.user_data['vk_height'] = h
    return True

async def vk_package_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_group_name'] = update.message.text
    await update.message.reply_text("Укажите **тематику** группы:", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_THEME

async def vk_package_theme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_theme'] = update.message.text
    await update.message.reply_text("Перечислите **товары** (через запятую):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_PRODUCTS

async def vk_package_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_products'] = update.message.text
    await update.message.reply_text("Перечислите **услуги** (через запятую):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_SERVICES

async def vk_package_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_services'] = update.message.text
    await update.message.reply_text("Напишите **преимущества** (через запятую):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_ADVANTAGES

async def vk_package_advantages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_advantages'] = update.message.text
    await update.message.reply_text("Введите **цвета оформления** (например: #FF5733, синий, серый):", reply_markup=get_cancel_keyboard())
    return VK_PACKAGE_COLORS

async def vk_package_colors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    context.user_data['vk_colors'] = update.message.text
    await update.message.reply_text(
        "✅ Параметры сохранены!\n\n"
        "Теперь выберите элемент упаковки.\n"
        "Сначала будет создан фон (без текста), затем вы сможете наложить текст.",
        reply_markup=get_vk_package_element_keyboard()
    )
    return VK_PACKAGE_ELEMENT_SELECT

async def vk_package_element_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    group = context.user_data.get('vk_group_name', 'Название')
    theme = context.user_data.get('vk_theme', '')
    colors = context.user_data.get('vk_colors', '#FFFFFF')
    products = context.user_data.get('vk_products', '')
    services = context.user_data.get('vk_services', '')
    advantages = context.user_data.get('vk_advantages', '')

    if text == "🖥 Обложка ПК (1920×768)":
        w, h, elem = 1920, 768, "обложка ПК"
        prompt_bg = f"Создай фон для обложки ВК. Тема: {theme}. Цвета: {colors}. Без текста. Размер {w}×{h}."
    elif text == "📱 Мобильная обложка (1080×1920)":
        w, h, elem = 1080, 1920, "мобильная обложка"
        prompt_bg = f"Создай фон для мобильной обложки ВК. Тема: {theme}. Цвета: {colors}. Без текста. Размер {w}×{h}."
    elif text == "🔘 Кнопки меню (376×256)":
        w, h, elem = 376, 256, "кнопка меню"
        prompt_bg = f"Создай минималистичный фон для кнопки меню ВК. Цвета: {colors}. Без текста. Размер {w}×{h}."
    elif text == "📊 Виджеты (480×720) ×3":
        w, h, elem = 480, 720, "виджет"
        prompt_bg = f"Создай фон для виджета ВК. Тема: {theme}. Цвета: {colors}. Без текста. Размер {w}×{h}."
        success = await generate_multiple_backgrounds(update, context, prompt_bg, w, h, elem)
        if not success:
            return MAIN_MENU
        await update.message.reply_text(
            f"✅ Три фона для виджетов готовы.\n\n"
            f"Теперь введите текст или используйте сохранённые данные.\n\n"
            f"*Сохранённые данные:*\nНазвание: {group}\nТовары: {products}\nУслуги: {services}\nПреимущества: {advantages}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Использовать сохранённые", callback_data="vk_use_saved")],
                [InlineKeyboardButton("✏️ Ввести свой текст", callback_data="vk_custom_text")],
                [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
            ]),
            parse_mode="Markdown"
        )
        return VK_PACKAGE_AWAIT_TEXT_CUSTOM
    elif text == "👤 Аватарка (1080×1080)":
        w, h, elem = 1080, 1080, "аватарка"
        prompt_bg = f"Создай фон для аватарки ВК. Тема: {theme}. Цвета: {colors}. Без текста. Размер {w}×{h}."
    elif text == "🛍 Товары (карточки для магазина, 1:1)":
        w, h, elem = 800, 800, "карточка товара"
        prompt_bg = f"Создай фон для карточки товара в магазине ВК. Тема: {theme}. Цвета: {colors}. Без текста. Размер {w}×{h}."
    elif text == "📁 Обложка подборки (1:1)":
        w, h, elem = 1200, 1200, "обложка подборки"
        prompt_bg = f"Создай фон для обложки подборки товаров ВК. Тема: {theme}. Цвета: {colors}. Без текста. Размер {w}×{h}."
    else:
        await update.message.reply_text("Пожалуйста, выберите элемент из меню.", reply_markup=get_vk_package_element_keyboard())
        return VK_PACKAGE_ELEMENT_SELECT

    context.user_data['vk_elem_type'] = elem
    context.user_data['vk_width'] = w
    context.user_data['vk_height'] = h

    await update.message.reply_text(f"🖼 Генерирую фон для {elem}... (до 30 секунд)")
    img_bytes, url = await generate_background_image(prompt_bg, w, h)
    if img_bytes:
        context.user_data['vk_background_bytes'] = img_bytes
        compressed = await compress_image(img_bytes)
        await update.message.reply_photo(
            photo=io.BytesIO(compressed),
            caption=f"✅ Фон для {elem} готов.\n\n"
                    f"Теперь введите текст или используйте сохранённые данные.\n\n"
                    f"*Сохранённые данные:*\nНазвание: {group}\nТовары: {products}\nУслуги: {services}\nПреимущества: {advantages}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Использовать сохранённые", callback_data="vk_use_saved")],
                [InlineKeyboardButton("✏️ Ввести свой текст", callback_data="vk_custom_text")],
                [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
            ]),
            parse_mode="Markdown"
        )
        return VK_PACKAGE_AWAIT_TEXT_CUSTOM
    else:
        await update.message.reply_text("❌ Не удалось сгенерировать фон. Попробуйте ещё раз.")
        return VK_PACKAGE_ELEMENT_SELECT

async def vk_handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "vk_use_saved":
        text_data = {
            'title': context.user_data.get('vk_group_name', 'Название'),
            'advantages': context.user_data.get('vk_advantages', ''),
            'products': context.user_data.get('vk_products', ''),
            'services': context.user_data.get('vk_services', ''),
            'colors': context.user_data.get('vk_colors', '#FFFFFF'),
        }
        context.user_data['vk_text_data'] = text_data
        await query.message.reply_text("✅ Использую сохранённые данные. Генерирую финальное изображение...")
        await generate_final_image(update, context, query.message)
    elif query.data == "vk_custom_text":
        await query.message.reply_text(
            "Введите текст в формате:\n\n"
            "Название группы: ...\n"
            "Товары: товар1, товар2, ...\n"
            "Услуги: услуга1, услуга2, ...\n"
            "Преимущества: преимущество1, преимущество2, ...",
            reply_markup=get_cancel_keyboard()
        )
        return VK_PACKAGE_AWAIT_TEXT_CUSTOM
    elif query.data == "main_menu":
        context.user_data.clear()
        await query.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

async def vk_custom_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text
    if user_text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    text_data = {
        'title': context.user_data.get('vk_group_name', 'Название'),
        'advantages': '',
        'products': '',
        'services': '',
        'colors': context.user_data.get('vk_colors', '#FFFFFF'),
    }
    lines = user_text.split('\n')
    for line in lines:
        low = line.lower()
        if 'название' in low:
            text_data['title'] = line.split(':', 1)[-1].strip()
        elif 'товар' in low:
            text_data['products'] = line.split(':', 1)[-1].strip()
        elif 'услуг' in low:
            text_data['services'] = line.split(':', 1)[-1].strip()
        elif 'преимуществ' in low:
            text_data['advantages'] = line.split(':', 1)[-1].strip()
    context.user_data['vk_text_data'] = text_data
    await update.message.reply_text("✅ Текст принят. Генерирую финальное изображение...")
    await generate_final_image(update, context, update.message)
    return VK_PACKAGE_ELEMENT_SELECT

async def generate_final_image(update, context, message):
    user_id = update.effective_user.id
    text_data = context.user_data.get('vk_text_data', {})
    elem_type = context.user_data.get('vk_elem_type', 'изображение')
    width = context.user_data.get('vk_width', 1920)
    height = context.user_data.get('vk_height', 768)
    backgrounds = context.user_data.get('vk_backgrounds')
    if backgrounds:
        for i, bg_bytes in enumerate(backgrounds, 1):
            img_with_text = add_text_to_image(bg_bytes, text_data, target_size=(width, height))
            compressed = await compress_image(img_with_text)
            await message.reply_photo(photo=io.BytesIO(compressed), caption=f"📊 Виджет {i}")
        await message.reply_text("✅ Все виджеты готовы!", reply_markup=get_main_keyboard())
    else:
        bg_bytes = context.user_data.get('vk_background_bytes')
        if not bg_bytes:
            await message.reply_text("❌ Ошибка: фон не найден. Начните заново.")
            return
        img_with_text = add_text_to_image(bg_bytes, text_data, target_size=(width, height))
        compressed = await compress_image(img_with_text)
        await message.reply_photo(photo=io.BytesIO(compressed), caption=f"🖼 {elem_type} готово!")
        await message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    save_message(user_id, "user", f"Упаковка ВК: {elem_type}")
    save_message(user_id, "assistant", "Изображение сгенерировано")

# ------------------- ПЛАТЕЖИ (Stars и Robokassa) -------------------
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

# ------------------- ВЕБ-СЕРВЕР ДЛЯ ROBOKASSA -------------------
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

# ------------------- ЗАПУСК -------------------
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
            AWAIT_FACE_SWAP_TARGET: [MessageHandler(filters.PHOTO, handle_face_swap_target), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_face_swap_target)],
            AWAIT_FACE_SWAP_SOURCE: [MessageHandler(filters.PHOTO, handle_face_swap_source), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_face_swap_source)],
            AWAIT_IMAGE_FOR_EDIT: [MessageHandler(filters.PHOTO, handle_edit_image), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_image)],
            AWAIT_PROMPT_FOR_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_prompt)],
            AWAIT_IMAGE_FOR_AVATAR: [MessageHandler(filters.PHOTO, handle_avatar_image), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_image)],
            AWAIT_AUDIO_FOR_AVATAR: [MessageHandler(filters.AUDIO | filters.VOICE, handle_avatar_audio), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avatar_audio)],
            AWAIT_VIDEO_FOR_ANIMATE: [MessageHandler(filters.VIDEO, handle_animate_video), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_video)],
            AWAIT_IMAGE_FOR_ANIMATE: [MessageHandler(filters.PHOTO, handle_animate_image), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_image)],
            AWAIT_IMAGE_ONLY: [MessageHandler(filters.PHOTO, handle_single_image), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_single_image)],
            POPULAR_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_popular_menu)],
            AWAIT_PROMPT_FOR_DEEPSEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deepseek_prompt)],
            AWAIT_PROMPT_FOR_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_to_image)],
            AWAIT_PHOTO_FOR_ANIMATE: [MessageHandler(filters.PHOTO, handle_animate_photo_photo), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_photo)],
            AWAIT_PROMPT_FOR_ANIMATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_animate_photo_prompt)],
            AWAIT_RESIZE_IMAGE: [MessageHandler(filters.PHOTO, handle_resize_image), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resize_image)],
            AWAIT_RESIZE_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resize_size)],
            VK_PACKAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_name)],
            VK_PACKAGE_THEME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_theme)],
            VK_PACKAGE_PRODUCTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_products)],
            VK_PACKAGE_SERVICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_services)],
            VK_PACKAGE_ADVANTAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_advantages)],
            VK_PACKAGE_COLORS: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_colors)],
            VK_PACKAGE_ELEMENT_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_element_select)],
            VK_PACKAGE_BACKGROUND_GENERATED: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_package_element_select)],
            VK_PACKAGE_AWAIT_TEXT_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, vk_custom_text_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(vk_handle_text_input, pattern="^(vk_use_saved|vk_custom_text|main_menu)$"))
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(CommandHandler("add_balance", add_balance_command))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(inline_topup_callback, pattern="topup"))
    app.add_handler(CallbackQueryHandler(copy_prompt_callback, pattern="^copy_(classic|hightech)$"))

    port = int(os.getenv("PORT", 8080))
    web_task = asyncio.create_task(run_web_server_with_robokassa(port, app.bot))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    logger.info("Бот запущен")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Остановка")
    finally:
        web_task.cancel()
        try:
            await web_task
        except asyncio.CancelledError:
            pass
        await app.stop()
        await app.updater.stop()

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")

if __name__ == "__main__":
    main()
