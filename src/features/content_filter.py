# content_filter.py
import asyncio
import google.generativeai as genai
import src.core.config as config
from src.core.logger import logger

# Промпт для проверки содержимого новости
content_check_prompt = """
Ты - система классификации новостных сообщений. Твоя задача - определить, относится ли входящее сообщение к одной из следующих категорий:

1. Коммерческая реклама (полностью рекламное сообщение)
2. Сообщение о ракетной опасности/опасности БПЛа или отбой таких опасностей

Правила:
- Если сообщение полностью является коммерческой рекламой ИЛИ содержит информацию о ракетной опасности/опасности БПЛа/отбое опасности - ответь только "YES"
- Во всех остальных случаях - ответь только "NO"

Определения:
- Коммерческая реклама: сообщения, полностью направленные на продажу товаров/услуг, объявления о скидках, акциях, промо-предложениях
- Сообщения об опасности: предупреждения о воздушной тревоге, ракетной атаке, угрозе БПЛа, отбои тревог

Твой ответ должен содержать ТОЛЬКО "YES" или "NO" без пояснений.
"""

async def check_content(text: str) -> bool:
    """
    Проверяет содержимое новости через Google AI API.
    
    Args:
        text: Текст новости для проверки
        
    Returns:
        bool: True если сообщение нужно отфильтровать (реклама или объявление опасности),
              False если сообщение подходит для переформулировки
    """
    errors = []
    
    # Используем список моделей в обратном порядке для фильтрации
    # (более легкие модели в приоритете для простых задач)
    reversed_models = list(reversed(config.AI_MODELS))
    logger.info(f"Content filter using models in reverse order: {reversed_models}")
    
    # Перебираем модели в обратном порядке
    for model_name in reversed_models:
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
                        "parts": [content_check_prompt]
                    },
                ])
                
                # Отправляем запрос и получаем ответ
                response = await chat.send_message(text)
                
                # Проверяем и возвращаем ответ
                if response and hasattr(response, 'text'):
                    logger.info(f"Content check successfully used model {model_name} with API key {key[:4]}***")
                    result = response.text.strip().upper()
                    return result == "YES"  # True если YES (нужно отфильтровать), False если NO (можно переформулировать)
                
                logger.warning(f"Empty response from content check model {model_name} with API key {key[:4]}***")
            except Exception as e:
                error_msg = f"Content check error with model {model_name}, API key {key[:4]}***: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
            
    # Если все модели и ключи не сработали, выводим подробную информацию об ошибках
    error_summary = "".join(errors)
    logger.critical(f"Content check: All models and API keys failed:\n{error_summary}")
    
    # В случае ошибки пропускаем сообщение (не фильтруем его)
    # Можно изменить это поведение в зависимости от требований
    return False 