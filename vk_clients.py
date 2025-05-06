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
        logger.warning("VK_TOKEN не настроен в .env, парсинг ВК не будет активирован")
        return False
    
    logger.info(f"Начинаю инициализацию клиента VK API с токеном: {config.VK_TOKEN[:5]}...")
    
    try:
        # Создаем асинхронную сессию с токеном
        logger.info("Создаю TokenSession для VK API")
        session = TokenSession(access_token=config.VK_TOKEN)
        vk_client = API(session)
        
        # Проверяем подключение запросом информации о пользователе с ID 1
        logger.info("Выполняю тестовый запрос к VK API (users.get)")
        test = await vk_client.users.get(user_ids=1)
        
        logger.info(f"Тестовый запрос к VK API выполнен, ответ: {test}")
        
        if test and isinstance(test, list) and len(test) > 0:
            logger.info(f"VK API клиент успешно инициализирован, ответ API: {test}")
            
            # Проверяем группы для мониторинга
            if not config.VK_GROUP_IDS:
                logger.warning("VK_GROUP_IDS не настроен в .env, список групп для мониторинга пуст")
            else:
                logger.info(f"Найдено {len(config.VK_GROUP_IDS)} групп ВК для мониторинга: {config.VK_GROUP_IDS}")
                for group_id in config.VK_GROUP_IDS:
                    try:
                        # Проверяем доступность группы
                        group_info = await vk_client.groups.getById(group_id=group_id)
                        logger.info(f"Группа {group_id} доступна: {group_info}")
                    except Exception as e:
                        logger.error(f"Ошибка при проверке группы {group_id}: {e}")
                
            return True
        else:
            logger.error(f"Ошибка инициализации VK API: неверный ответ на тестовый запрос: {test}")
            return False
    except Exception as e:
        logger.error(f"Ошибка инициализации VK API: {e}", exc_info=True)
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
    else:
        logger.warning("VK API клиент не был инициализирован или уже закрыт") 