import os
import re
import aiohttp
import src.core.config as config
from src.core.logger import logger
import json

# Constants for Cortex API
CORTEX_API_URL = "https://cortex-api.vercel.app/v1/chat/completions"
CORTEX_MODEL = "claude-sonnet-4" # Assuming Claude Sonnet is the model to use

# Get API key from environment variable
CORTEX_API_KEY = os.getenv("CORTEX_API_KEY")

if not CORTEX_API_KEY:
    logger.error("CORTEX_API_KEY environment variable not set. Cortex API functions will not work.")

# Системный промпт для переформулирования новости
default_prompt = """
<role>
Ты – профессиональный помощник по редактуре и оформлению новостей для Telegram-канала.
</role>

<goal>
Преобразовать входной текст в валидный HTML-код для Telegram, создав краткую, динамичную и информативную новость с высокой вовлеченностью читателей.
</goal>

<language_style>
<primary_language>русский</primary_language>
<tone>краткий, динамичный, информативный</tone>
<engagement>высокая вовлеченность через выделение ключевых моментов</engagement>
<neutrality>строгая нейтральность и объективность</neutrality>
<forbidden_elements>
- субъективные оценки
- личные мнения
- призывы к подписке
- рекламные вставки
</forbidden_elements>
</language_style>

<html_formatting>
<allowed_tags>
- &lt;b&gt; для ключевых слов, имен, цифр (умеренно)
- &lt;i&gt; для смыслового выделения и тональности
- &lt;u&gt; для подчеркивания
- &lt;s&gt; для зачеркивания
- &lt;blockquote&gt; ТОЛЬКО для развернутых цитат и прямой речи
- &lt;code&gt; для кода
- &lt;pre&gt; для предформатированного текста
- &lt;a&gt; для ссылок
</allowed_tags>

<paragraph_structure>
- Разделение на логические абзацы двойным переносом строк (\n\n)
- ЗАПРЕЩЕНО использовать &lt;br&gt; или &lt;p&gt;
</paragraph_structure>

<quote_formatting>
<blockquote_usage>
- Только для развернутых цитат и прямой речи
- Никогда не добавлять перед ними эмодзи или символы (●, —, ➤, ☑)
- Помнить: в Telegram отображаются как отдельный блок с новой строки
</blockquote_usage>
<short_quotes>
- Для коротких цитат и упоминаний использовать обычные кавычки («»)
- НЕ использовать тег &lt;blockquote&gt; для коротких цитат
</short_quotes>
</quote_formatting>

<forbidden_markdown>
- Никакого Markdown: **, __, *, _, [], (), ```, &gt;, #
- Не экранировать символы &lt;, &gt;, &amp; внутри тегов
</forbidden_markdown>
</html_formatting>

<emoji_rules>
<selection>Выбрать ОДИН главный эмодзи, отражающий тему новости</selection>
<placement>Начать ответ с эмодзи и пробела</placement>
</emoji_rules>

<content_processing>
<preserve>
- Ключевую информацию: факты, цифры, имена
- Структуру и логику изложения
</preserve>

<remove>
- Все ссылки (кроме части прямых цитат или связанных с новостью)
- Хэш-теги
- Рекламные вставки
- Опросы (вопросы с вариантами ответов, включая эмодзи)
- Упоминания источников: "Источник сообщил", "По информации издания", "По данным агентства"
</remove>
</content_processing>

<output_format>
<structure>Только финальный HTML-код новости, начиная с главного эмодзи</structure>
<forbidden_wrappers>
- НЕ ДОБАВЛЯТЬ ```html в начале
- НЕ ДОБАВЛЯТЬ ``` в конце
- Никаких маркеров Markdown кода
</forbidden_wrappers>
<purity>Чистый HTML без дополнительных обозначений или аннотаций</purity>
<response_language>Всегда отвечать на русском языке</response_language>
</output_format>

<quality_control>
<validation>Проверить валидность всех HTML-тегов</validation>
<readability>Убедиться в легкости восприятия текста</readability>
<engagement>Оценить потенциал вовлечения читателей</engagement>
</quality_control>
"""

# Шаблон для модификации существующего текста
modification_prompt_template = """
<role>
Ты – HTML-редактор новостей для Telegram, специализирующийся на доработке уже созданного контента.
</role>

<goal>
Переформатировать существующий HTML-текст согласно специфическим требованиям, сохранив структуру и содержание.
</goal>

<input_structure>
<source_text>{text}</source_text>
<custom_requirements>{custom_prompt}</custom_requirements>
</input_structure>

<html_compliance>
<allowed_tags>
- &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;s&gt;, &lt;blockquote&gt;, &lt;code&gt;, &lt;pre&gt;, &lt;a&gt;
</allowed_tags>

<structure_preservation>
- Сохранить структуру абзацев с двойным переносом строки (\n\n)
- Сохранить начальный эмодзи
- Сохранить символы в начале абзацев
</structure_preservation>

<quote_handling>
- Прямая речь должна быть в тегах &lt;blockquote&gt;…&lt;/blockquote&gt;
</quote_handling>
</html_compliance>

<output_restrictions>
<forbidden_wrappers>
- НЕ ДОБАВЛЯТЬ ```html в начале
- НЕ ДОБАВЛЯТЬ ``` в конце
- Никаких маркеров Markdown кода
</forbidden_wrappers>
<purity>Чистый HTML без дополнительных обозначений или аннотаций</purity>
</output_restrictions>

<processing_priority>
1. Применить пользовательские требования из {custom_prompt}
2. Обеспечить HTML-совместимость
3. Сохранить исходную структуру и смысл
4. Проверить валидность тегов
</processing_priority>

<output_format>
<content>Только финальный HTML-код без дополнительных комментариев</content>
<validation>Убедиться в корректности всех HTML-тегов</validation>
</output_format>
"""

content_check_prompt_cortex = """
<role>
Ты - автоматическая система классификации и фильтрации новостных сообщений.
</role>

<goal>
Определить, относится ли входящее сообщение к категориям, требующим специального обработки или исключения из публикации.
</goal>

<classification_categories>
<category id="1">
<name>Коммерческая реклама</name>
<description>Полностью рекламное сообщение</description>
<criteria>
- Сообщения, полностью направленные на продажу товаров/услуг
- Объявления о скидках, акциях, промо-предложениях
- Призывы к покупке или заказу услуг
- Контент с основной целью коммерческого продвижения
</criteria>
</category>

<category id="2">
<name>Сообщения о безопасности</name>
<description>Информация о ракетной опасности/опасности БПЛа или отбой таких опасностей</description>
<criteria>
- Предупреждения о воздушной тревоге
- Сообщения о ракетной атаке
- Информация об угрозе БПЛа (беспилотных летательных аппаратов)
- Отбои тревог и сигналов опасности
- Официальные предупреждения о чрезвычайных ситуациях
</criteria>
</category>
</classification_categories>

<decision_logic>
<positive_match>
<condition>Если сообщение полностью является коммерческой рекламой</condition>
<result>YES</result>
</positive_match>

<positive_match>
<condition>ИЛИ содержит информацию о ракетной опасности/опасности БПЛа/отбоя опасности</condition>
<result>YES</result>
</positive_match>

<negative_match>
<condition>Во всех остальных случаях</condition>
<result>NO</result>
</negative_match>
</decision_logic>

<analysis_process>
<step_1>Проанализировать основную цель сообщения</step_1>
<step_2>Проверить соответствие критериям категории 1 (коммерческая реклама)</step_2>
<step_3>Проверить соответствие критериям категории 2 (сообщения о безопасности)</step_3>
<step_4>Принять решение на основе логики принятия решений</step_4>
</analysis_process>

<output_format>
<response_type>Строго бинарный ответ</response_type>
<allowed_responses>
- "YES" - если сообщение соответствует любой из категорий
- "NO" - если сообщение не соответствует ни одной категории
</allowed_responses>
<forbidden_elements>
- Пояснения
- Комментарии  
- Дополнительный текст
- Обоснования решения
</forbidden_elements>
<format>Ответ должен содержать ТОЛЬКО "YES" или "NO"</format>
</output_format>

<quality_assurance>
<accuracy>Обеспечить точную классификацию без ложноположительных результатов</accuracy>
<consistency>Применять критерии последовательно ко всем сообщениям</consistency>
<speed>Быстрое принятие решения без избыточного анализа</speed>
</quality_assurance>
"""

async def _get_cortex_headers(api_key: str) -> dict:
    """
    Формирует заголовки для запроса к Cortex API.
    """
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

async def _make_cortex_request(system_prompt: str, user_content: str, temperature: float = 0.7) -> str | None:
    """
    Отправляет запрос к Cortex API и возвращает ответ.
    """
    if not CORTEX_API_KEY:
        logger.error("CORTEX_API_KEY is not set. Cannot make API request.")
        return None

    headers = await _get_cortex_headers(CORTEX_API_KEY)
    payload = {
        "assistant": {
            "name": "Claude",
            "instructions": system_prompt,
            "temperature": temperature,
            "model": CORTEX_MODEL,
            "capabilities": {}
        },
        "messages": [
            {
                "role": "user",
                "content": user_content,
            }
        ]
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(CORTEX_API_URL, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()
                logger.debug(f"Raw Cortex API response: {json.dumps(result, ensure_ascii=False, indent=2)}")
                if result and isinstance(result, dict) and "result" in result and result["result"]:
                    for item in result["result"]:
                        if "content" in item:
                            raw_content = item["content"]
                            cleaned_content = None
                            if isinstance(raw_content, str):
                                temp_content = re.sub(r"<anon>thinking>.*?<\/anon>thinking>", "", raw_content, flags=re.DOTALL)
                                cleaned_content = re.sub(r"<[^>]*?(?:thinking|anon)[^>]*?>.*?<\/[^>]*?(?:thinking|anon)[^>]*?>", "", temp_content, flags=re.DOTALL).strip()
                                # Added logic to handle plain 'thinking>' marker
                                if 'thinking>' in cleaned_content:
                                    parts = cleaned_content.split('thinking>', 1)
                                    if len(parts) > 1:
                                        cleaned_content = parts[1].strip()
                                    else:
                                        logger.warning("Found 'thinking>' in string content but split did not yield two parts. Original content may be malformed.")
                            elif isinstance(raw_content, list):
                                for content_item in raw_content:
                                    if content_item.get("type") == "text" and content_item.get("text"):
                                        temp_content = re.sub(r"<anon>thinking>.*?<\/anon>thinking>", "", content_item["text"], flags=re.DOTALL)
                                        cleaned_content = re.sub(r"<[^>]*?(?:thinking|anon)[^>]*?>.*?<\/[^>]*?(?:thinking|anon)[^>]*?>", "", temp_content, flags=re.DOTALL).strip()
                                        # Added logic to handle plain 'thinking>' marker in list item
                                        if 'thinking>' in cleaned_content:
                                            parts = cleaned_content.split('thinking>', 1)
                                            if len(parts) > 1:
                                                cleaned_content = parts[1].strip()
                                            else:
                                                logger.warning("Found 'thinking>' in list item but split did not yield two parts. Original content may be malformed.")
                                        break
                            if cleaned_content:
                                logger.debug(f"Cleaned Cortex API response content: {cleaned_content}")
                                return cleaned_content
                logger.warning(f"Unexpected response structure from Cortex API: {result}")
                return None
        except aiohttp.ClientError as e:
            logger.error(f"Client error during Cortex API request: {e}")
            return None
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON response from Cortex API.")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during Cortex API request: {e}")
            return None

async def reformulate_text(text: str) -> str:
    """
    Переформулирует текст через Cortex API.
    """
    response_content = await _make_cortex_request(default_prompt, text, temperature=0.7)
    if response_content:
        logger.info("Successfully reformulated text using Cortex API. Response: %s", response_content)
        return response_content
    else:
        logger.error("Failed to reformulate text using Cortex API. Empty or erroneous response.")
        raise Exception("Failed to reformulate text")

async def check_content_with_cortex(text: str) -> bool:
    """
    Проверяет содержимое новости через Cortex API.
    """
    response_content = await _make_cortex_request(content_check_prompt_cortex, text, temperature=0.0)
    if response_content:
        match = re.search(r"\b(YES|NO)\b\s*$", response_content.strip().upper())
        if match:
            result = match.group(1)
            if result == "YES":
                logger.info("Content check with Cortex API: Filtered (YES).")
                return True
            elif result == "NO":
                logger.info("Content check with Cortex API: Not filtered (NO).")
                return False
        logger.warning(f"Unexpected response from content check model: {response_content}")
        return False
    else:
        logger.error("Failed to perform content check with Cortex API. Empty or erroneous response.")
        return False

async def modify_text_with_custom_prompt(reformulated_text: str, custom_prompt: str) -> str:
    """
    Модифицирует уже переформулированный текст с использованием кастомного промпта через Cortex API.
    """
    full_prompt = modification_prompt_template.format(text=reformulated_text, custom_prompt=custom_prompt)
    response_content = await _make_cortex_request(modification_prompt_template, full_prompt, temperature=0.7)
    if response_content:
        logger.info("Successfully modified text using Cortex API.")
        return response_content
    else:
        logger.error("Failed to modify text using Cortex API. Empty or erroneous response.")
        raise Exception("Failed to modify text") 