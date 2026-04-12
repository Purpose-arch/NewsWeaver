import asyncio
import re
from openai import AsyncOpenAI
import src.core.config as config
from src.core.logger import logger

# Initialize the OpenAI client using settings
client = AsyncOpenAI(
    api_key=config.settings.llm_api_key.get_secret_value(),
    base_url=config.settings.llm_base_url,
)

MODEL_NAME = config.settings.llm_model_name

# Prompt templates
DEFAULT_PROMPT = (
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
    "   ● Выбери ОДИН главный эмодзи, отражающий тему новости.\n"
    "   ● Каждый следующий абзац (после первого) начинай с подходящего эмодзи или символа (●, —, ➤, ☑) и пробела.\n"
    "\n"
    "4. Содержание\n"
    "   ● Сохрани ключевую информацию: факты, цифры, имена.\n"
    "   ● Удали все ссылки, хэш-теги и рекламные вставки, если они не часть прямой цитаты.\n"
    "   ● Удали любые опросы (вопросы с вариантами ответов, включая эмодзи).\n"
    "   ● Удали все упоминания источников новости, такие как «Источник сообщил», «По информации издания», «По данным агентства» и т.п.\n"
    "\n"
    "5. Выходные данные\n"
    "   ● В ответе только финальный HTML-код новости, начиная с главного эмодзи.\n"
    "   ● Никакого markdown блока ```html в начале или ``` в конце. Только чистый HTML.\n"
)

MODIFICATION_PROMPT = (
    "Ты – HTML-редактор новостей для Telegram.\n\n"
    "Переформатируй следующий HTML-текст согласно указанным требованиям:\n"
    "{text}\n\n"
    "Требования HTML-форматирования:\n"
    "● Используй только теги: <b>, <i>, <u>, <s>, <blockquote>, <code>, <pre>, <a>, <tg-spoiler>\n"
    "● Сохрани структуру абзацев с двойным переносом строки (\\n\\n)\n"
    "● Сохрани начальный эмодзи и символы в начале абзацев\n"
    "● Прямая речь должна быть в тегах <blockquote>…</blockquote>\n\n"
    "Основные требования:\n"
    "{custom_prompt}\n\n"
    "В ответе только финальный HTML-код без markdown блока ```html."
)

CONTENT_CHECK_PROMPT = """
Ты - система классификации новостных сообщений. Твоя задача - определить, относится ли входящее сообщение к одной из следующих категорий:

1. Коммерческая реклама (полностью рекламное сообщение, призывы к покупке, скидки).
2. Сообщение об опасности (предупреждения о ракетной опасности, БПЛА, воздушной тревоге, или отбой таких тревог).

Правила:
- Если сообщение полностью является рекламой ИЛИ содержит информацию о ракетной опасности/опасности БПЛА/отбое опасности - ответь только "YES".
- Во всех остальных случаях (например, обычные новости) - ответь только "NO".
Твой ответ должен содержать ТОЛЬКО "YES" или "NO" без пояснений.
"""


def clean_response(text: str) -> str:
    """Removes markdown code blocks if the model unexpectedly wraps the output in them."""
    text = text.strip()
    if text.startswith("```html"):
        text = text[len("```html") :]
    elif text.startswith("```"):
        text = text[len("```") :]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


async def reformulate_text(text: str) -> str:
    """
    Reformulates text via the LLM API.
    """
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": DEFAULT_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.7,
            timeout=45.0,
        )
        content = response.choices[0].message.content
        if not content:
            raise Exception("LLM returned empty response")
        return clean_response(content)
    except Exception as e:
        logger.error(f"Error during reformulate_text: {e}")
        raise


async def modify_text_with_custom_prompt(
    reformulated_text: str, custom_prompt: str
) -> str:
    """
    Modifies an already reformulated text using a custom prompt.
    """
    prompt = MODIFICATION_PROMPT.format(
        text=reformulated_text, custom_prompt=custom_prompt
    )
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "Переформатируй текст согласно указанным требованиям.",
                },
            ],
            temperature=0.7,
            timeout=45.0,
        )
        content = response.choices[0].message.content
        if not content:
            raise Exception("LLM returned empty response")
        return clean_response(content)
    except Exception as e:
        logger.error(f"Error during modify_text_with_custom_prompt: {e}")
        raise


async def check_content(text: str) -> bool:
    """
    Checks if the text is an ad or a danger warning (for filtering).
    Returns True if the message should be filtered.
    """
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": CONTENT_CHECK_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            timeout=30.0,
        )
        content = response.choices[0].message.content
        if not content:
            return False

        result = content.strip().upper()
        match = re.search(r"\b(YES|NO)\b\s*$", result)
        if match:
            found = match.group(1)
            if found == "YES":
                logger.info("Content check: Filtered (YES).")
                return True
            else:
                return False

        logger.warning(f"Unexpected response from content check: {result}.")
        return False

    except Exception as e:
        logger.error(f"Error during check_content: {e}")
        return False
