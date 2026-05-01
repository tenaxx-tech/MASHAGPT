import aiohttp
import asyncio
import logging
from typing import List, Tuple, Optional

from openai import AsyncOpenAI

from config import BOTHUB_API_KEY, BOTHUB_OPENAI_BASE_URL, BOTHUB_REPLICATE_BASE_URL

logger = logging.getLogger(__name__)

# ------------------- OpenAI-совместимый клиент для текста -------------------
openai_client = AsyncOpenAI(
    api_key=BOTHUB_API_KEY,
    base_url=BOTHUB_OPENAI_BASE_URL,
)

async def bothub_text_generate(prompt: str, history: List[Tuple[str, str]], model: str) -> str:
    """
    Генерация текста через Bothub OpenAI API.
    history: список (role, content) – роль "user" или "assistant".
    """
    messages = []
    for role, content in history[-5:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    try:
        response = await openai_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1024,
            temperature=1.0,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.exception(f"Ошибка Bothub text: {e}")
        raise Exception(f"Ошибка генерации текста: {str(e)}")

# ------------------- Replicate API через Bothub -------------------
async def bothub_media_generate(model: str, payload: dict) -> tuple[bytes, str]:
    """
    Отправляет запрос к Replicate API Bothub, дожидается результата,
    возвращает (file_bytes, media_url)
    """
    url = f"{BOTHUB_REPLICATE_BASE_URL}/images/generations"  # базовый эндпоинт
    # Для видео и аудио могут быть другие эндпоинты, но в документации Bothub
    # все медиа идут через /images/generations. Уточняем по факту:
    if "video" in model.lower():
        # Предполагаем, что видео тоже через этот эндпоинт
        pass
    headers = {
        "Authorization": f"Bearer {BOTHUB_API_KEY}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"model": model, "input": payload}, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Bothub Replicate error {resp.status}: {text}")
            data = await resp.json()
            # Ожидаем {"urls": ["https://..."]} или {"urls": [...]}
            urls = data.get("urls")
            if not urls or not isinstance(urls, list):
                raise Exception(f"Неверный ответ Bothub: {data}")
            media_url = urls[0]
            # Скачиваем файл
            async with session.get(media_url) as img_resp:
                if img_resp.status != 200:
                    raise Exception(f"Ошибка скачивания файла: {img_resp.status}")
                file_bytes = await img_resp.read()
            return file_bytes, media_url

# Для удобства создаём обёртки под разные типы
async def bothub_image_generate(prompt: str, model: str, aspect_ratio: str = "1:1") -> tuple[bytes, str]:
    payload = {"prompt": prompt, "aspect_ratio": aspect_ratio, "num_outputs": 1}
    return await bothub_media_generate(model, payload)

async def bothub_image_edit(image_url: str, prompt: str, model: str) -> tuple[bytes, str]:
    """"""
    payload = {"image": image_url, "prompt": prompt}
    return await bothub_media_generate(model, payload)

async def bothub_video_generate(prompt: str, model: str, image_url: Optional[str] = None) -> tuple[bytes, str]:
    payload = {"prompt": prompt}
    if image_url:
        payload["imageUrl"] = image_url
    return await bothub_media_generate(model, payload)

async def bothub_animate_photo(image_url: str, mode: str, prompt: Optional[str] = None) -> tuple[bytes, str]:
    payload = {"imageUrl": image_url, "mode": mode}
    if prompt:
        payload["prompt"] = prompt
    return await bothub_media_generate("grok-imagine-image-to-video", payload)
