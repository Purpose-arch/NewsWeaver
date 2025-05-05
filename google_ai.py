# google_ai.py
import asyncio
import google.generativeai as genai
import config
from logger import logger

# Те же шаблоны промптов, что и в requesty.py
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
    "   ● Удали все упоминания источников новости, такие как «Источник сообщил», «По информации издания», «По данным агентства» и т.п.\n"
    "\n"
    "5. Выходные данные\n"
    "   ● В ответе только финальный HTML-код новости, начиная с главного эмодзи.\n"
    "   ● Всегда отвечай на русском языке.\n"
)

# Шаблон для модификации существующего текста
modification_prompt = (
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
    "В ответе только финальный HTML-код."
)

async def reformulate_text(text: str) -> str:
    """
    Переформулирует текст через Google AI API.
    Циклично перебирает ключи GOOGLE_AI_API_KEYS, обрабатывает ошибки.
    """
    for key in config.GOOGLE_AI_API_KEYS:
        try:
            # Настраиваем API ключ
            genai.configure(api_key=key)
            
            # Получаем модель
            model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
            
            # Создаем запрос с системным промптом и пользовательским сообщением
            chat = model.start_chat(history=[
                {
                    "role": "user",
                    "parts": [default_prompt]
                },
            ])
            
            # Отправляем запрос и получаем ответ
            response = await asyncio.to_thread(
                chat.send_message,
                text,
            )
            
            # Проверяем и возвращаем ответ
            if response and hasattr(response, 'text'):
                return response.text.strip()
            
            logger.warning(f"Empty response from Google AI API with key {key}")
        except Exception as e:
            logger.error(f"Google AI API exception with key {key}: {e}")
        
        # Небольшая задержка перед использованием следующего ключа
        await asyncio.sleep(1)
    
    raise Exception("All Google AI API keys failed")

async def modify_text_with_custom_prompt(reformulated_text: str, custom_prompt: str) -> str:
    """
    Модифицирует уже переформулированный текст с использованием кастомного промпта через Google AI API.
    """
    prompt = modification_prompt.format(text=reformulated_text, custom_prompt=custom_prompt)
    
    for key in config.GOOGLE_AI_API_KEYS:
        try:
            # Настраиваем API ключ
            genai.configure(api_key=key)
            
            # Получаем модель
            model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
            
            # Создаем запрос с системным промптом и пользовательским сообщением
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
            )
            
            # Проверяем и возвращаем ответ
            if response and hasattr(response, 'text'):
                return response.text.strip()
            
            logger.warning(f"Empty response from Google AI API with key {key}")
        except Exception as e:
            logger.error(f"Google AI API exception with key {key}: {e}")
        
        # Небольшая задержка перед использованием следующего ключа
        await asyncio.sleep(1)
    
    raise Exception("All Google AI API keys failed") 