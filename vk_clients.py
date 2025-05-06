import asyncio
from aiovk import TokenSession, API
import config
from logger import logger

# Глобальный VK API клиент
vk_client = None

async def start_vk_client():
    """
    Инициализирует клиент API ВКонтакте
    """
    global vk_client
    
    if not config.VK_TOKEN:
        logger.warning("VK_TOKEN не настроен, парсинг ВК не будет активирован")
        return False
    
    try:
        # Создаем асинхронную сессию с токеном
        session = TokenSession(access_token=config.VK_TOKEN)
        vk_client = API(session)
        
        # Проверяем подключение
        test = await vk_client.users.get(user_ids=1)
        if test and isinstance(test, list) and len(test) > 0:
            logger.info(f"VK API клиент успешно инициализирован")
            return True
        else:
            logger.error(f"Ошибка инициализации VK API: неверный ответ на тестовый запрос")
            return False
    except Exception as e:
        logger.error(f"Ошибка инициализации VK API: {e}")
        return False

async def close_vk_client():
    """
    Закрывает соединения с API ВКонтакте
    """
    global vk_client
    
    if vk_client and hasattr(vk_client, '_session') and hasattr(vk_client._session, 'close'):
        try:
            await vk_client._session.close()
            logger.info("VK API клиент закрыт")
        except Exception as e:
            logger.error(f"Ошибка при закрытии VK API клиента: {e}") 