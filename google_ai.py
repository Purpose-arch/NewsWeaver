# google_ai.py
import asyncio
import google.generativeai as genai
import config
from logger import logger


default_prompt = (
    "Ты – профессиональный редактор новостей для Telegram-канала.
Твоя задача – преобразовать входной новостной текст в валидный HTML-код для Telegram, строго соблюдая следующие правила:

1. Язык и стиль
   ● Пиши кратко, нейтрально и объективно на русском языке.
   ● Удали субъективные оценки, мнения и призывы к подписке.

2. Форматирование и теги
   ● ИСПОЛЬЗУЙ ТОЛЬКО HTML-ТЕГИ: <b>, <i>, <u>, <s>, <blockquote>, <code>, <pre>, <a>, <tg-spoiler>.
   ● НИКОГДА не используй Markdown-разметку (**, __, *, _, [], (), `, >, # и т.д.).
   ● Разделяй текст на логические абзацы двойным переносом строки (\\n\\n). НЕ используй <br> или <p>.
   ● Прямая речь и цитаты всегда оформляются в отдельный блок тегом <blockquote>...</blockquote> с новой строки.
   ● ВАЖНО: Никогда не начинай <blockquote> с эмодзи или специальных символов (●, —, ➤, ☑️). Эти символы должны быть на отдельной строке перед цитатой.
   ● Для коротких цитат в тексте используй обычные кавычки («»), а НЕ тег <blockquote>.
   ● Выделяй важные элементы тегом <b>...</b>, а не **жирный текст**.

3. Эмодзи и символы
   ● ТОЛЬКО ПЕРВЫЙ абзац новости начинай с одного тематического эмодзи и пробела (🏛, 💰, 🔬, 🌪, ⚔️, 🏆, 🎭, 🏥, 📚, 👥).
   ● Каждый последующий абзац начинай с подходящего символа (●, —, ➤, ☑️) и пробела.
   ● Если следующий абзац является цитатой (<blockquote>), символ размещай в отдельной строке перед цитатой.

4. Содержание
   ● Сохрани ключевую информацию: факты, цифры, имена.
   ● Удали все ссылки, хэш-теги и рекламные вставки, если они не часть прямой цитаты.
   ● Удали любые опросы и упоминания источников новости.

5. Структура ответа
   ● Твой ответ должен содержать ТОЛЬКО финальный HTML-код новости.
   ● Начинай ответ с главного эмодзи и пробела.
   ● НЕ добавляй маркеры кода, тройные обратные кавычки или пометки "html".

ПРИМЕРЫ ФОРМАТИРОВАНИЯ:
1. Правильно (для цитат):
⚔️ В Курской области произошла атака на трассу Курск-Рыльск.

● В результате пострадали <b>12 мирных жителей</b>, среди них <b>двое детей</b>.

— Все раненые доставлены в больницу.

<blockquote>Знаю, что это такое и какие могут быть последствия, если дрон попадет в машину. Я принял решение, насколько позволяла обстановка, сбавить скорость автомобиля и на ходу выпрыгнуть из него.</blockquote>

2. Неправильно:
⚔️ <blockquote>В Курской области произошла атака</blockquote>

● <blockquote>Все раненые доставлены в больницу</blockquote>

— **Пострадали 12 человек**"
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
    "● Прямая речь должна быть в тегах <blockquote>…</blockquote>\n"
    "● НЕ ДОБАВЛЯЙ ```html в начале и ``` в конце ответа. Никаких маркеров Markdown кода.\n"
    "● Отвечай ЧИСТЫМ HTML без каких-либо дополнительных обозначений или аннотаций.\n\n"
    "Основные требования:\n"
    "{custom_prompt}\n\n"
    "В ответе только финальный HTML-код."
)

async def reformulate_text(text: str) -> str:
    """
    Переформулирует текст через Google AI API.
    Использует систему fallback: перебирает все модели и ключи.
    """
    errors = []
    
    # Перебираем все модели из списка
    for model_name in config.AI_MODELS:
        # Для каждой модели пробуем все ключи API
        for key in config.GOOGLE_AI_API_KEYS:
            try:
                # Настраиваем API ключ
                genai.configure(api_key=key)
                
                # Получаем модель
                model = genai.GenerativeModel(model_name)
                
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
                    logger.info(f"Successfully used model {model_name} with API key {key[:4]}***")
                    return response.text.strip()
                
                logger.warning(f"Empty response from model {model_name} with API key {key[:4]}***")
            except Exception as e:
                error_msg = f"Error with model {model_name}, API key {key[:4]}***: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
            
            # Небольшая задержка перед использованием следующего ключа
            await asyncio.sleep(1)
    
    # Если все модели и ключи не сработали, выводим подробную информацию об ошибках
    error_summary = "\n".join(errors)
    logger.critical(f"All models and API keys failed:\n{error_summary}")
    raise Exception("All models and API keys failed")

async def modify_text_with_custom_prompt(reformulated_text: str, custom_prompt: str) -> str:
    """
    Модифицирует уже переформулированный текст с использованием кастомного промпта через Google AI API.
    Использует систему fallback: перебирает все модели и ключи.
    """
    prompt = modification_prompt.format(text=reformulated_text, custom_prompt=custom_prompt)
    errors = []
    
    # Перебираем все модели из списка
    for model_name in config.AI_MODELS:
        # Для каждой модели пробуем все ключи API
        for key in config.GOOGLE_AI_API_KEYS:
            try:
                # Настраиваем API ключ
                genai.configure(api_key=key)
                
                # Получаем модель
                model = genai.GenerativeModel(model_name)
                
                # Создаем запрос с промптом
                response = await asyncio.to_thread(
                    model.generate_content,
                    prompt,
                )
                
                # Проверяем и возвращаем ответ
                if response and hasattr(response, 'text'):
                    logger.info(f"Successfully used model {model_name} with API key {key[:4]}***")
                    return response.text.strip()
                
                logger.warning(f"Empty response from model {model_name} with API key {key[:4]}***")
            except Exception as e:
                error_msg = f"Error with model {model_name}, API key {key[:4]}***: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
            
            # Небольшая задержка перед использованием следующего ключа
            await asyncio.sleep(1)
    
    # Если все модели и ключи не сработали, выводим подробную информацию об ошибках
    error_summary = "\n".join(errors)
    logger.critical(f"All models and API keys failed:\n{error_summary}")
    raise Exception("All models and API keys failed") 
