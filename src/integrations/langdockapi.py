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
default_prompt = (
    "<prompt_instructions>\n"
    "  <system_role>Ты – профессиональный помощник по редактуре и оформлению новостей для Telegram-канала.</system_role>\n"
    "  <task_description>Твоя задача – преобразовать входной новостной текст в ТОЛЬКО валидный HTML-код для Telegram, строго соблюдая указанные правила.</task_description>\n"
    "  <section name=\"LanguageAndStyle\">\n"
    "    <rule>Пиши кратко, динамично и информативно на русском языке. Стремись к высокой вовлеченности читателя, выделяя ключевые моменты, но всегда сохраняй нейтральность и объективность.</rule>\n"
    "    <rule>Удали субъективные оценки, мнения и призывы к подписке.</rule>\n"
    "  </section>\n"
    "  <section name=\"FormattingAndTags\">\n"
    "    <rule>Разрешены только теги: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;s&gt;, &lt;blockquote&gt;, &lt;code&gt;, &lt;pre&gt;, &lt;a&gt;.</rule>\n"
    "    <rule>Разделяй текст на логические абзацы двойным переносом строк. НЕ используй &lt;br&gt; или &lt;p&gt;.</rule>\n"
    "    <rule>Прямая речь и цитаты (из кавычек) обязательно оформляй тегом &lt;blockquote&gt;…&lt;/blockquote&gt; и никогда не добавляй перед ними эмодзи или символы (никаких ●, —, ➤, ☑).</rule>\n"
    "    <rule>Используй тег &lt;blockquote&gt; ТОЛЬКО для развёрнутых цитат и прямой речи, так как в Telegram они всегда отображаются с новой строки как отдельный блок.</rule>\n"
    "    <rule>Для коротких цитат и упоминаний в тексте используй обычные кавычки («»), а НЕ тег &lt;blockquote&gt;.</rule>\n"
    "    <rule>Выделяй ключевые слова, имена и цифры тегом &lt;b&gt;…&lt;/b&gt; умеренно.</rule>\n"
    "    <rule>Используй тег &lt;i&gt;…&lt;/i&gt; для смыслового выделения или для передачи тональности в уместных случаях.</rule>\n"
    "    <rule>НЕ используй Markdown-разметку (**, __, *, _, [], (), `, &gt;, # и т.д.) и не экранируй символы &lt;, &gt;, &amp; внутри тегов.</rule>\n"
    "  </section>\n"
    "  <section name=\"Emoji\">\n"
    "    <rule>Выбери ОДИН главный эмодзи, отражающий тему новости. Начни ответ с него и пробела.</rule>\n"
    "  </section>\n"
    "  <section name=\"Content\">\n"
    "    <rule>Сохрани ключевую информацию: факты, цифры, имена.</rule>\n"
    "    <rule>Удали все ссылки, хэш-теги и рекламные вставки, если они не часть прямой цитаты или не связаны с самой новостью.</rule>\n"
    "    <rule>Удали любые опросы (вопросы с вариантами ответов, включая эмодзи).</rule>\n"
    "    <rule>Удали все упоминания источников новости, такие как «Источник сообщил», «По информации издания», «По данным агентства» и т.п.</rule>\n"
    "  </section>\n"
    "  <section name=\"Output\">\n"
    "    <rule>В ответе только финальный HTML-код новости, начиная с главного эмодзи.</rule>\n"
    "    <rule>НЕ ДОБАВЛЯЙ ```html в начале и ``` в конце ответа. Никаких маркеров Markdown кода.</rule>\n"
    "    <rule>Отвечай ЧИСТЫМ HTML без каких-либо дополнительных обозначений или аннотаций.</rule>\n"
    "    <rule>Всегда отвечай на русском языке.</rule>\n"
    "  </section>\n"
    "</prompt_instructions>"
)


modification_prompt_template = (
    "<prompt_modification>\n"
    "  <system_role>Ты – HTML-редактор новостей для Telegram.</system_role>\n"
    "  <reformatting_instructions>\n"
    "    Переформатируй следующий HTML-текст согласно указанным требованиям:\n"
    "    {text}\n"
    "    Требования HTML-форматирования:\n"
    "  </reformatting_instructions>\n"
    "  <html_formatting_requirements>\n"
    "    <rule>Используй только теги: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;s&gt;, &lt;blockquote&gt;, &lt;code&gt;, &lt;pre&gt;, &lt;a&gt;.</rule>\n"
    "    <rule>Сохрани структуру абзацев с двойным переносом строки (\\n\\n)</rule>\n"
    "    <rule>Сохрани начальный эмодзи и символы в начале абзацев</rule>\n"
    "    <rule>Прямая речь должна быть в тегах &lt;blockquote&gt;…&lt;/blockquote&gt;</rule>\n"
    "    <rule>НЕ ДОБАВЛЯЙ ```html в начале и ``` в конце ответа. Никаких маркеров Markdown кода.</rule>\n"
    "    <rule>Отвечай ЧИСТЫМ HTML без каких-либо дополнительных обозначений или аннотаций.</rule>\n"
    "  </html_formatting_requirements>\n"
    "  <main_requirements>\n"
    "    Основные требования:\n"
    "    {custom_prompt}\n"
    "  </main_requirements>\n"
    "  <output_rule>В ответе только финальный HTML-код.</output_rule>\n"
    "</prompt_modification>"
)

# Промпт для проверки содержимого новости для Langdock
content_check_prompt_langdock = """
<prompt_for_content_check>
  <system_role>Ты - система классификации новостных сообщений.</system_role>
  <task>Твоя задача - определить, относится ли входящее сообщение к одной из следующих категорий:</task>
  <categories>
    <category>1. Коммерческая реклама (полностью рекламное сообщение)</category>
    <category>2. Сообщение о ракетной опасности/опасности БПЛа или отбой таких опасностей</category>
  </categories>
  <rules>
    <rule>Если сообщение полностью является коммерческой рекламой ИЛИ содержит информацию о ракетной опасности/опасности БПЛа/отбое опасности - ответь только "YES"</rule>
    <rule>Во всех остальных случаях - ответь только "NO"</rule>
  </rules>
  <definitions>
    <definition name="Коммерческая реклама">сообщения, полностью направленные на продажу товаров/услуг, объявления о скидках, акциях, промо-предложениях</definition>
    <definition name="Сообщения об опасности">предупреждения о воздушной тревоге, ракетной атаке, угрозе БПЛа, отбои тревог</definition>
  </definitions>
  <output_format>Твой ответ должен содержать ТОЛЬКО "YES" или "NO" без пояснений.</output_format>
</prompt_for_content_check>
"""

async def _load_langdock_api_keys() -> list[str]:
    """
    Загружает активные API ключи Langdock из JSON файла.
    """
    keys = []
    try:
        file_path_src_utils = os.path.join(os.path.dirname(__file__), "..", "utils", ACTIVE_LANGDOCK_API_KEYS_FILE)

        if os.path.exists(file_path_src_utils):
            file_to_read = file_path_src_utils
        else:
            logger.warning(f"Langdock API keys file not found at {file_path_src_utils}. Generating new keys.")
            _key_generation_enabled_event.set() # Trigger generation if file is missing
            return []

        f = await asyncio.to_thread(open, file_to_read, 'r', encoding='utf-8')
        with f:
            data = json.load(f)
            # Expected format is a list of strings
            if isinstance(data, list) and all(isinstance(key, str) for key in data):
                keys = data
            else:
                logger.warning(f"Unexpected data format in {file_to_read}. Starting with an empty list of keys.")
                _key_generation_enabled_event.set() # Trigger generation if format is wrong
                return []
            
            logger.info(f"Loaded {len(keys)} Langdock API keys from {file_to_read}.")
    except json.JSONDecodeError:
        logger.warning(f"Corrupt or empty JSON file: {ACTIVE_LANGDOCK_API_KEYS_FILE}. Returning empty list of keys and triggering generation.")
        _key_generation_enabled_event.set() # Trigger generation if file is corrupt
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
                            elif isinstance(raw_content, list):
                                for content_item in raw_content:
                                    if content_item.get("type") == "text" and content_item.get("text"):
                                        temp_content = re.sub(r"<anon>thinking>.*?<\/anon>thinking>", "", content_item["text"], flags=re.DOTALL)
                                        cleaned_content = re.sub(r"<[^>]*?(?:thinking|anon)[^>]*?>.*?<\/[^>]*?(?:thinking|anon)[^>]*?>", "", temp_content, flags=re.DOTALL).strip()
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