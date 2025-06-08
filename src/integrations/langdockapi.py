# src/integrations/langdockapi.py
import asyncio
import aiohttp
import json
import os
import src.core.config as config # Предполагается, что конфиг будет здесь
from src.core.logger import logger # Предполагается, что логгер будет здесь

# URL Langdock API
LANGDOCK_API_URL = "https://api.langdock.com/assistant/v1/chat/completions"

# Путь к файлу с API ключами Langdock
LANGDOCK_API_KEYS_FILE = "langdock_api_keys.json" # Будет находиться в корне проекта или в src/utils, позже уточним

# Системный промпт для переформулирования новости (используем тот же, что и в voidapi_ai.py)
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
    "   ● Разделяй текст на логические абзацы двойным переносом строк. НЕ используй <br> или <p>.\n"
    "   ● Прямая речь и цитаты (из кавычек) обязательно оформляй тегом <blockquote>…</blockquote> и никогда не добавляй перед ними эмодзи или символы (никаких ●, —, ➤, ☑).\n"
    "   ● Используй тег <blockquote> ТОЛЬКО для развёрнутых цитат и прямой речи, так как в Telegram они всегда отображаются с новой строки как отдельный блок.\n"
    "   ● Для коротких цитат и упоминаний в тексте используй обычные кавычки («»), а НЕ тег <blockquote>.\n"
    "   ● Выделяй ключевые слова, имена и цифры тегом <b>…</b> умеренно.\n"
    "   ● НЕ используй Markdown-разметку (**, __, *, _, [], (), `, >, # и т.д.) и не экранируй символы <, >, & внутри тегов.\n"
    "\n"
    "3. Эмодзи и символы\n"
    "   ● Выбери ОДИН главный эмодзи, отражающий тему новости. Начни ответ с него и пробела.\n"
    "   ● Каждый следующий абзац (после первого) начинай с подходящего эмодзи или символа (●, —, ➤, ☑) и пробела.\n"
    "\n"
    "4. Содержание\n"
    "   ● Сохрани ключевую информацию: факты, цифры, имена.\n"
    "   ● Удали все ссылки, хэш-теги и рекламные вставки, если они не часть прямой цитаты или не связаны с самой новостью.\n"
    "   ● Удали любые опросы (вопросы с вариантами ответов, включая эмодзи).\n"
    "   ● Удали все упоминания источников новости, такие как «Источник сообщил», «По информации издания», «По данным агентства» и т.п.\n"
    "\n"
    "5. Выходные данные\n"
    "   ● В ответе только финальный HTML-код новости, начиная с главного эмодзи.\n"
    "   ● НЕ ДОБАВЛЯЙ ```html в начале и ``` в конце ответа. Никаких маркеров Markdown кода.\n"
    "   ● Отвечай ЧИСТЫМ HTML без каких-либо дополнительных обозначений или аннотаций.\n"
    "   ● Всегда отвечай на русском языке.\n"
)

# Шаблон для модификации существующего текста
modification_prompt_template = (
    "Ты – HTML-редактор новостей для Telegram.\n\n"
    "Переформатируй следующий HTML-текст согласно указанным требованиям:\n"
    "{text}\n\n"
    "Требования HTML-форматирования:\n"
    "● Используй только теги: <b>, <i>, <u>, <s>, <blockquote>, <code>, <pre>, <a>, <tg-spoiler>\n"
    "● Сохрани структуру абзацев с двойным переносом строки (\\n\\n)\n"
    "● Сохрани начальный эмодзи и символы в начале абзацев\n"
    "● Прямая речь должна быть в тегах <blockquote>…</blockquote>\n"
    "● НЕ ДОБАВЛЯЙ ```html в начале и ``` в конце ответа. Никаких маркеров Markdown кода.\n"
    "● Отвечай ЧИСТЫМ HTML без каких-либо дополнительных обозначений или аннотаций.\n\n"
    "Основные требования:\n"
    "{custom_prompt}\n\n"
    "В ответе только финальный HTML-код."
)

async def _load_langdock_api_keys() -> list[str]:
    """
    Загружает API ключи Langdock из JSON файла.
    """
    keys = []
    try:
        # Для простоты, пока что предположим, что он будет в корне или в src/utils
        # Если файл будет в src/utils, то путь будет src/utils/langdock_api_keys.json
        # DEPRECATED: file_path_root = os.path.join(os.getcwd(), LANGDOCK_API_KEYS_FILE)
        file_path_src_utils = os.path.join(os.path.dirname(__file__), "..", "utils", LANGDOCK_API_KEYS_FILE)


        # DEPRECATED: if os.path.exists(file_path_root):
        # DEPRECATED:     file_to_read = file_path_root
        if os.path.exists(file_path_src_utils):
            file_to_read = file_path_src_utils
        else:
            logger.warning(f"Langdock API keys file not found at {file_path_src_utils}.")
            return []

        f = await asyncio.to_thread(open, file_to_read, 'r', encoding='utf-8')
        with f:
            data = json.load(f)
            # Извлекаем ключи, у которых "if_working": true
            keys = [key for key, value in data.items() if value.get("if_working", False)]
            logger.info(f"Loaded {len(keys)} Langdock API keys from {file_to_read}.")
    except json.JSONDecodeError:
        logger.warning(f"Corrupt or empty JSON file: {LANGDOCK_API_KEYS_FILE}. Returning empty list of keys.")
    except Exception as e:
        logger.error(f"Error loading Langdock API keys: {e}")
    return keys

async def _get_langdock_headers(api_key: str) -> dict:
    """
    Формирует заголовки для запроса к Langdock API.
    """
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

async def _make_langdock_request(payload: dict, api_key: str) -> str | None:
    """
    Отправляет запрос к Langdock API и возвращает ответ.
    """
    headers = await _get_langdock_headers(api_key)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(LANGDOCK_API_URL, json=payload, headers=headers) as response:
                response.raise_for_status()  # Выбросит исключение для статусов 4xx/5xx
                result = await response.json()
                # Извлекаем контент из ответа Langdock, аналогично langdockexample.py
                # response = httpx.post(url, json=payload, headers=headers)
                # print(response.json())
                # Langdock API возвращает немного другую структуру, чем OpenAI, нужно адаптировать
                # Если смотреть на langdockexample.py, там просто ответ от httpx, без разбора структуры.
                # Предположим, что контент будет в 'choices[0].message.content' или аналогично OpenAI
                # На основе langdockexample.py видно, что структура может быть прямо в response.json()
                # Однако, чтобы быть более устойчивым, попробуем предусмотреть структуру OpenAI-like
                if result and isinstance(result, dict) and "choices" in result and result["choices"]:
                    if result["choices"][0].get("message") and result["choices"][0]["message"].get("content"):
                        return result["choices"][0]["message"]["content"].strip()
                logger.warning(f"Unexpected response structure from Langdock API: {result}")
                return None
        except aiohttp.ClientError as e:
            logger.error(f"Client error during Langdock API request: {e}")
            return None
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON response from Langdock API.")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during Langdock API request: {e}")
            return None

async def reformulate_text(text: str) -> str:
    """
    Переформулирует текст через Langdock API.
    Использует систему fallback: перебирает все доступные ключи.
    """
    errors = []
    # Langdock, в отличие от VoidAI, не имеет "моделей", явно указываемых в запросе,
    # модель обычно определяется на стороне ассистента или по умолчанию.
    # Так как в langdockexample.py указана "model": "o3", будем использовать её.
    langdock_model = "claude-sonnet-4@20250514" # Предполагаем, что это будет константа или из конфига

    # Загружаем ключи Langdock
    keys_to_try = await _load_langdock_api_keys()

    if not keys_to_try:
        logger.critical("No Langdock API keys found or configured.")
        raise Exception("No Langdock API keys configured")

    for key in keys_to_try:
        try:
            payload = {
                "assistant": {
                    "name": "Claude", # Имя ассистента из langdockexample.py
                    "instructions": default_prompt, # Используем наш промпт
                    "temperature": 0.7,
                    "model": langdock_model,
                    "capabilities": {}
                },
                "messages": [
                    {
                        "role": "user",
                        "content": text,
                    }
                ]
            }

            response_content = await _make_langdock_request(payload, key)

            if response_content:
                logger.info(f"Successfully used Langdock API with key {key[:4]}*** for reformulation.")
                return response_content

            logger.warning(f"Empty response from Langdock API with key {key[:4]}*** during reformulation.")
        except Exception as e:
            error_msg = f"Error with Langdock API key {key[:4]}*** during reformulation: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        await asyncio.sleep(1) # Небольшая задержка перед использованием следующего ключа

    error_summary = "\n".join(errors)
    logger.critical(f"All Langdock API keys failed for text reformulation:\n{error_summary}")
    raise Exception("All Langdock API keys failed for text reformulation")

async def modify_text_with_custom_prompt(reformulated_text: str, custom_prompt: str) -> str:
    """
    Модифицирует уже переформулированный текст с использованием кастомного промпта через Langdock API.
    Использует систему fallback: перебирает все доступные ключи.
    """
    prompt = modification_prompt_template.format(text=reformulated_text, custom_prompt=custom_prompt)
    errors = []
    langdock_model = "claude-sonnet-4@20250514" # Предполагаем, что это будет константа или из конфига

    keys_to_try = await _load_langdock_api_keys()

    if not keys_to_try:
        logger.critical("No Langdock API keys found or configured.")
        raise Exception("No Langdock API keys configured")

    for key in keys_to_try:
        try:
            payload = {
                "assistant": {
                    "name": "Claude",
                    "instructions": "", # Для модификации инструкцию можно опустить или задать общую
                    "temperature": 0.7,
                    "model": langdock_model,
                    "capabilities": {}
                },
                "messages": [
                    {
                        "role": "user",
                        "content": prompt, # Кастомный промпт как пользовательское сообщение
                    }
                ]
            }

            response_content = await _make_langdock_request(payload, key)

            if response_content:
                logger.info(f"Successfully used Langdock API with key {key[:4]}*** for modification.")
                return response_content

            logger.warning(f"Empty response from Langdock API with key {key[:4]}*** during modification.")
        except Exception as e:
            error_msg = f"Error with Langdock API key {key[:4]}*** during modification: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        await asyncio.sleep(1)

    error_summary = "\n".join(errors)
    logger.critical(f"All Langdock API keys failed for text modification:\n{error_summary}")
    raise Exception("All Langdock API keys failed for text modification") 