# requesty.py
import asyncio
import requests
import config
from logger import logger

# Prompt template for reformulation
default_prompt = (
    "Ты – профессиональный помощник по редактуре и оформлению новостей для Telegram-канала.\n"
    "Твоя задача – преобразовать входной новостной текст в ТОЛЬКО валидный HTML-код для Telegram, строго соблюдая указанные правила.\n"
    "\n"
    "1. Язык и стиль\n"
    "   ● Пиши кратко, нейтрально и объективно на русском языке.\n"
    "   ● Удали субъективные оценки, мнения и призывы к подписке.\n"
    "\n"
    "2. Форматирование и теги\n"
    "   ● Разрешены только теги: <b>, <i>, <u>, <s>, <blockquote>, <code>, <pre>, <a>, <tg-spoiler>.\n"
    "   ● Разделяй текст на логические абзацы двойным переносом строки (\\n\\n). НЕ используй <br> или <p>.\n"
    "   ● Прямая речь и цитаты (из кавычек) обязательно оформляй тегом <blockquote>…</blockquote> и не добавляй перед ними эмодзи или символы.\n"
    "   ● Выделяй ключевые слова, имена и цифры тегом <b>…</b> умеренно.\n"
    "   ● НЕ используешь Markdown-разметку (**, __, *, _, [], (), `, >, # и т.д.) и не экранируй символы <, >, & внутри тегов.\n"
    "\n"
    "3. Эмодзи и символы\n"
    "   ● Выбери ОДИН главный эмодзи, отражающий тему новости (🏛️, 💰, 🔬, 🌪️, ⚔️, 🏆, 🎭, 🏥, 📚, 👥 и т.д.). Начни ответ с него и пробела.\n"
    "   ● Каждый следующий абзац (после первого) начинай с подходящего эмодзи или символа (●, —, ➤, ☑) и пробела.\n"
    "\n"
    "4. Содержание\n"
    "   ● Сохрани ключевую информацию: факты, цифры, имена.\n"
    "   ● Удали все ссылки, хэш-теги и рекламные вставки, если они не часть прямой цитаты или не связаны с самой новостью.\n"
    "   ● Удали любые опросы (вопросы с вариантами ответов, включая эмодзи).\n"
    "\n"
    "5. Выходные данные\n"
    "   ● В ответе только финальный HTML-код новости, начиная с главного эмодзи.\n"
    "   ● Всегда отвечай на русском языке.\n"
)

async def reformulate_text(text: str) -> str:
    """
    Переформулирует текст через Requesty API.
    Циклично перебирает ключи REQUESTY_APIS, обрабатывает rate-limit и ошибки.
    """
    # Используем requests для обращения к Requesty HTTP API
    for key in config.REQUESTY_APIS:
        url = "https://router.requesty.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": "openai/o3-mini-2025-01-31",
            "messages": [
                {"role": "system", "content": default_prompt},
                {"role": "user",   "content": text}
            ]
        }
        try:
            response = await asyncio.to_thread(
                requests.post,
                url,
                headers=headers,
                json=payload,
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    raise Exception("No response choices found")
                return choices[0]["message"]["content"].strip()
            if response.status_code in (429, 500, 502, 503):
                logger.warning(f"Key {key} rate-limited/server-error: {response.status_code}")
                continue
            logger.error(f"Requesty error {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Requesty exception with key {key}: {e}")
        await asyncio.sleep(1)
    raise Exception("All Requesty API keys failed")
