# content_filter.py
import asyncio
# DEPRECATED: import google.generativeai as genai
import src.core.config as config
from src.core.logger import logger
from src.integrations.cortexapi import check_content_with_cortex

# Промпт для проверки содержимого новости
# DEPRECATED: content_check_prompt = """
# DEPRECATED: Ты - система классификации новостных сообщений. Твоя задача - определить, относится ли входящее сообщение к одной из следующих категорий:
# DEPRECATED: 
# DEPRECATED: 1. Коммерческая реклама (полностью рекламное сообщение)
# DEPRECATED: 2. Сообщение о ракетной опасности/опасности БПЛа или отбой таких опасностей
# DEPRECATED: 
# DEPRECATED: Правила:
# DEPRECATED: - Если сообщение полностью является коммерческой рекламой ИЛИ содержит информацию о ракетной опасности/опасности БПЛа/отбоя опасности - ответь только "YES"
# DEPRECATED: - Во всех остальных случаях - ответь только "NO"
# DEPRECATED: 
# DEPRECATED: Определения:
# DEPRECATED: - Коммерческая реклама: сообщения, полностью направленные на продажу товаров/услуг, объявления о скидках, акциях, промо-предложениях
# DEPRECATED: - Сообщения об опасности: предупреждения о воздушной тревоге, ракетной атаке, угрозе БПЛа, отбои тревог
# DEPRECATED: 
# DEPRECATED: Твой ответ должен содержать ТОЛЬКО "YES" или "NO" без пояснений.
# DEPRECATED: """

async def check_content(text: str) -> bool:
    """
    Проверяет содержимое новости через Langdock API.
    
    Args:
        text: Текст новости для проверки
        
    Returns:
        bool: True если сообщение нужно отфильтровать (реклама или объявление опасности),
              False если сообщение подходит для переформулировки
    """
    try:
        return await check_content_with_cortex(text)
    except Exception as e:
        logger.critical(f"Critical error during content check with Cortex API: {e}. Defaulting to not filtered.")
        # В случае критической ошибки пропускаем сообщение (не фильтруем его)
        return False 