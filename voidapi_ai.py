# voidapi_ai.py
import asyncio
from openai import OpenAI
import config
from logger import logger

# Системный промпт для переформулирования новости
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

async def reformulate_text(text: str) -> str:
    """
    Переформулирует текст через VoidAI API (совместимый с OpenAI SDK).
    Использует систему fallback: перебирает все модели и ключи.
    """
    errors = []
    # Используем VOIDAI_MODELS и VOIDAI_API_KEYS из config
    models_to_try = getattr(config, 'VOIDAI_MODELS', ['claude-3-5-sonnet-20241022', 'gpt-4o', 'gemini-1.5-pro']) # Добавил дефолтные модели на всякий случай
    keys_to_try = getattr(config, 'VOIDAI_API_KEYS', [])

    if not keys_to_try:
         logger.critical("No VOIDAI_API_KEYS found in config.py")
         raise Exception("No VoidAI API keys configured")

    for model_name in models_to_try:
        for key in keys_to_try:
            try:
                # Инициализация клиента OpenAI с base_url VoidAI
                client = OpenAI(
                    api_key=key,
                    base_url="https://api.voidai.app/v1/"
                )

                # Создание сообщения для API
                messages = [
                    {"role": "system", "content": default_prompt},
                    {"role": "user", "content": text}
                ]

                # Отправка запроса
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model_name,
                    messages=messages,
                    # Дополнительные параметры могут быть добавлены здесь, если нужны
                    # например, temperature, max_tokens из документации VoidAI/OpenAI
                )

                # Проверка и возврат ответа
                if response and response.choices and response.choices[0].message and response.choices[0].message.content:
                    logger.info(f"Successfully used VoidAI model {model_name} with API key {key[:4]}***")
                    return response.choices[0].message.content.strip()

                logger.warning(f"Empty response from VoidAI model {model_name} with API key {key[:4]}***")
            except Exception as e:
                error_msg = f"Error with VoidAI model {model_name}, API key {key[:4]}***: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

            # Небольшая задержка перед использованием следующего ключа
            await asyncio.sleep(1)

    # Если все модели и ключи не сработали
    error_summary = "\n".join(errors)
    logger.critical(f"All VoidAI models and API keys failed:\n{error_summary}")
    raise Exception("All VoidAI models and API keys failed")

async def modify_text_with_custom_prompt(reformulated_text: str, custom_prompt: str) -> str:
    """
    Модифицирует уже переформулированный текст с использованием кастомного промпта через VoidAI API.
    Использует систему fallback: перебирает все модели и ключи.
    """
    prompt = modification_prompt_template.format(text=reformulated_text, custom_prompt=custom_prompt)
    errors = []
    # Используем VOIDAI_MODELS и VOIDAI_API_KEYS из config
    models_to_try = getattr(config, 'VOIDAI_MODELS', ['claude-3-5-sonnet-20241022', 'gpt-4o', 'gemini-1.5-pro']) # Добавил дефолтные модели на всякий случай
    keys_to_try = getattr(config, 'VOIDAI_API_KEYS', [])

    if not keys_to_try:
         logger.critical("No VOIDAI_API_KEYS found in config.py")
         raise Exception("No VoidAI API keys configured")

    for model_name in models_to_try:
        for key in keys_to_try:
            try:
                # Инициализация клиента OpenAI с base_url VoidAI
                client = OpenAI(
                    api_key=key,
                    base_url="https://api.voidai.app/v1/"
                )

                # Создание сообщения для API
                # Для модификации можно отправить весь промпт как пользовательское сообщение
                # или разделить на system и user, если это лучше работает.
                # Следую логике google_ai.py, где весь modification_prompt подается как один вход.
                messages = [{"role": "user", "content": prompt}]


                # Отправка запроса
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model_name,
                    messages=messages,
                    # Дополнительные параметры
                )

                # Проверка и возврат ответа
                if response and response.choices and response.choices[0].message and response.choices[0].message.content:
                    logger.info(f"Successfully used VoidAI model {model_name} with API key {key[:4]}***")
                    return response.choices[0].message.content.strip()

                logger.warning(f"Empty response from VoidAI model {model_name} with API key {key[:4]}***")
            except Exception as e:
                error_msg = f"Error with VoidAI model {model_name}, API key {key[:4]}***: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

            # Небольшая задержка перед использованием следующего ключа
            await asyncio.sleep(1)

    # Если все модели и ключи не сработали
    error_summary = "\n".join(errors)
    logger.critical(f"All VoidAI models and API keys failed:\n{error_summary}")
    raise Exception("All VoidAI models and API keys failed") 