# src/integrations/langdockapi.py
import asyncio
import aiohttp
import json
import os
import re
import src.core.config as config # Предполагается, что конфиг будет здесь
from src.core.logger import logger # Предполагается, что логгер будет здесь
from src.utils.langdock_key_gen import invalidate_and_generate_new_key, _key_generation_enabled_event

# URL Langdock API
LANGDOCK_API_URL = "https://api.langdock.com/assistant/v1/chat/completions"

# Путь к файлу с API ключами Langdock (теперь активными ключами)
ACTIVE_LANGDOCK_API_KEYS_FILE = "active_langdock_api_keys.json"

# Системный промпт для переформулирования новости (используем тот же, что и в voidapi_ai.py)
default_prompt = """
<role>
Ты – профессиональный помощник по редактуре и оформлению новостей для Telegram-канала.
</role>

<goal>
Преобразовать ЛЮБОЙ ВХОДНОЙ текст в валидный HTML-код для Telegram, создав краткую, динамичную и информативную новость с высокой вовлеченностью читателей.
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

content_check_prompt_langdock = """
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
<condition>ИЛИ содержит информацию о ракетной опасности/опасности БПЛа/отбое опасности</condition>
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

async def _load_langdock_api_keys() -> list[str]:
    """
    Загружает активные API ключи Langdock из JSON файла.
    """
    def _load_sync(path: str) -> list[str]:
        """Синхронный хелпер для атомарного чтения файла."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and all(isinstance(key, str) for key in data):
                    logger.info(f"Loaded {len(data)} Langdock API keys from {path}.")
                    return data
                else:
                    logger.warning(f"Unexpected data format in {path}. Starting with an empty list of keys.")
                    _key_generation_enabled_event.set()
                    return []
        except FileNotFoundError:
            logger.warning(f"Langdock API keys file not found at {path}. Generating new keys.")
            _key_generation_enabled_event.set()
            return []
        except json.JSONDecodeError:
            logger.warning(f"Corrupt or empty JSON file: {path}. Returning empty list of keys and triggering generation.")
            _key_generation_enabled_event.set()
            return []

    file_path = os.path.join(os.path.dirname(__file__), "..", "utils", ACTIVE_LANGDOCK_API_KEYS_FILE)
    
    try:
        keys = await asyncio.to_thread(_load_sync, file_path)
        return keys
    except Exception as e:
        logger.error(f"Error loading Langdock API keys: {e}")
        return []

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
                response.raise_for_status()
                result = await response.json()
                logger.debug(f"Raw Langdock API response: {json.dumps(result, ensure_ascii=False, indent=2)}")
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
                                logger.debug(f"Cleaned Langdock API response content: {cleaned_content}")
                                return cleaned_content
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
    Использует систему fallback: перебирает все доступные ключи, инвалидируя нерабочие.
    """
    errors = []
    langdock_model = "claude-sonnet-4-eu"
    keys_to_try = await _load_langdock_api_keys()

    if not keys_to_try:
        logger.critical("No Langdock API keys found or configured. Attempting to generate.")
        # Wait for generator to potentially create keys
        await asyncio.sleep(5) # Give some time for generation
        keys_to_try = await _load_langdock_api_keys() # Try loading again
        if not keys_to_try:
            raise Exception("No Langdock API keys configured or generated after waiting.")

    for key in list(keys_to_try): # Iterate over a copy, as keys_to_try might change
        try:
            payload = {
                "assistant": {
                    "name": "Claude",
                    "instructions": default_prompt,
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
            else:
                logger.warning(f"Empty response from Langdock API with key {key[:4]}*** during reformulation. Invalidating key.")
                await invalidate_and_generate_new_key(key)
                errors.append(f"Empty response with key {key[:4]}***")

        except Exception as e:
            error_msg = f"Error with Langdock API key {key[:4]}*** during reformulation: {str(e)}. Invalidating key."
            logger.error(error_msg)
            errors.append(error_msg)
            await invalidate_and_generate_new_key(key) # Invalidate the key on error

        await asyncio.sleep(1) # Small delay before trying next key

    error_summary = "\n".join(errors)
    logger.critical(f"All Langdock API keys failed for text reformulation:\n{error_summary}")
    raise Exception("All Langdock API keys failed for text reformulation")

async def check_content_with_langdock(text: str) -> bool:
    """
    Проверяет содержимое новости через Langdock API.
    Использует систему fallback: перебирает все доступные ключи, инвалидируя нерабочие.
    """
    errors = []
    langdock_model = "claude-sonnet-4-eu"

    keys_to_try = await _load_langdock_api_keys()

    if not keys_to_try:
        logger.critical("No Langdock API keys found or configured for content checking. Attempting to generate.")
        # Wait for generator to potentially create keys
        # Use a polling mechanism instead of fixed sleep
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 60: # 60 seconds timeout
            keys_to_try = await _load_langdock_api_keys()
            if keys_to_try:
                break
            await asyncio.sleep(1) # Check every second
        
        if not keys_to_try:
            raise Exception("No Langdock API keys configured or generated after waiting for content checking.")

    for key in list(keys_to_try): # Iterate over a copy, as keys_to_try might change
        try:
            payload = {
                "assistant": {
                    "name": "Claude",
                    "instructions": content_check_prompt_langdock,
                    "temperature": 0.0, # Низкая температура для классификации
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
                # Use regex to find YES or NO at the end of the string, ignoring any leading text including <thinking> blocks
                match = re.search(r"\b(YES|NO)\b\s*$", response_content.strip().upper())
                if match:
                    result = match.group(1)
                else:
                    result = None # No valid YES/NO found

                if result == "YES":
                    logger.info(f"Content check with Langdock API key {key[:4]}***: Filtered (YES).")
                    return True
                elif result == "NO":
                    logger.info(f"Content check with Langdock API key {key[:4]}***: Not filtered (NO).")
                    return False
                else:
                    logger.warning(f"Unexpected response from content check model {langdock_model} with API key {key[:4]}***: {response_content}. Invalidating key.")
                    await invalidate_and_generate_new_key(key)
                    errors.append(f"Unexpected response '{response_content}' with key {key[:4]}***")
            else:
                logger.warning(f"Empty response from content check model {langdock_model} with API key {key[:4]}***. Invalidating key.")
                await invalidate_and_generate_new_key(key)
                errors.append(f"Empty response with key {key[:4]}***")

        except Exception as e:
            error_msg = f"Error with Langdock API key {key[:4]}*** during content check: {str(e)}. Invalidating key."
            logger.error(error_msg)
            errors.append(error_msg)
            await invalidate_and_generate_new_key(key)

        await asyncio.sleep(1) # Small delay before trying next key

    error_summary = "\n".join(errors)
    logger.critical(f"All Langdock API keys failed for content checking:\n{error_summary}")
    raise Exception("All Langdock API keys failed for content checking")

async def modify_text_with_custom_prompt(reformulated_text: str, custom_prompt: str) -> str:
    """
    Модифицирует уже переформулированный текст с использованием кастомного промпта через Langdock API.
    Использует систему fallback: перебирает все доступные ключи, инвалидируя нерабочие.
    """
    prompt = modification_prompt_template.format(text=reformulated_text, custom_prompt=custom_prompt)
    errors = []
    langdock_model = "claude-sonnet-4-eu"

    keys_to_try = await _load_langdock_api_keys()

    if not keys_to_try:
        logger.critical("No Langdock API keys found or configured. Attempting to generate.")
        # Use a polling mechanism instead of fixed sleep
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 60: # 60 seconds timeout
            keys_to_try = await _load_langdock_api_keys()
            if keys_to_try:
                break
            await asyncio.sleep(1) # Check every second
        
        if not keys_to_try:
            raise Exception("No Langdock API keys configured or generated after waiting.")

    for key in list(keys_to_try): # Iterate over a copy
        try:
            payload = {
                "assistant": {
                    "name": "Claude",
                    "instructions": modification_prompt_template,
                    "temperature": 0.7,
                    "model": langdock_model,
                    "capabilities": {}
                },
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ]
            }

            response_content = await _make_langdock_request(payload, key)

            if response_content:
                logger.info(f"Successfully used Langdock API with key {key[:4]}*** for modification.")
                return response_content
            else:
                logger.warning(f"Empty response from Langdock API with key {key[:4]}*** during modification. Invalidating key.")
                await invalidate_and_generate_new_key(key)
                errors.append(f"Empty response with key {key[:4]}***")
        except Exception as e:
            error_msg = f"Error with Langdock API key {key[:4]}*** during modification: {str(e)}. Invalidating key."
            logger.error(error_msg)
            errors.append(error_msg)
            await invalidate_and_generate_new_key(key)

        await asyncio.sleep(1)

    error_summary = "\n".join(errors)
    logger.critical(f"All Langdock API keys failed for text modification:\n{error_summary}")
    raise Exception("All Langdock API keys failed for text modification") 