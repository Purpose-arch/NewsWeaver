import asyncio
import time
from datetime import datetime, timedelta
import config
import db
import google_ai
import moderation
import vk_clients
from logger import logger
import content_filter

async def _process_wall_post(owner_id, post_id, post_data, force_process=False):
    """
    Обрабатывает полученную публикацию из паблика ВК:
    дедуплицирует, реформулирует текст и отправляет на модерацию
    
    Args:
        owner_id: ID группы (отрицательный)
        post_id: ID поста
        post_data: Данные поста
        force_process: Флаг для принудительной обработки (игнорирует проверку на дубликаты)
    """
    # Формируем уникальный идентификатор поста
    post_id_str = f"{owner_id}_{post_id}"
    
    # Проверяем, обрабатывался ли такой пост ранее
    if not force_process and await db.check_processed(owner_id, post_id, source_type="vk"):
        logger.info(f"Пост {post_id_str} уже был обработан ранее, пропускаю")
        return
    
    logger.info(f"Обрабатываю пост {post_id_str}")
    
    # Помечаем пост как обработанный для избежания дублей
    if not force_process:
        await db.mark_processed(owner_id, post_id, source_type="vk")
    
    # Извлекаем текст из поста
    text = post_data.get('text', '').strip()
    if not text:
        logger.info(f"Пропуск пустого поста {post_id_str}")
        return
    
    logger.info(f"Исходный текст поста {post_id_str}: {text[:100]}...")
    
    # Проверяем содержимое на рекламу и объявления о ракетной опасности
    try:
        is_filtered = await content_filter.check_content(text)
        if is_filtered:
            logger.info(f"Пост отфильтрован (реклама или оповещение) {post_id_str}")
            return
    except Exception as e:
        logger.error(f"Ошибка проверки фильтра для поста {post_id_str}: {e}")
        # Если проверка не удалась, продолжаем обработку (не фильтруем)
    
    # Реформулируем текст через Google AI API
    try:
        logger.info(f"Начинаю реформулирование текста для поста {post_id_str}")
        reformulated = await google_ai.reformulate_text(text)
        logger.info(f"Реформулирование завершено для поста {post_id_str}: {reformulated[:100]}...")
    except Exception as e:
        logger.error(f"Ошибка реформулирования для {post_id_str}: {e}", exc_info=True)
        return

    # Отправляем сообщение на модерацию
    try:
        logger.info(f"Отправляю пост {post_id_str} на модерацию")
        await moderation.send_for_moderation(
            owner_id, 
            post_id,
            reformulated, 
            vk_clients.vk_client, 
            post_data,
            source_type="vk"
        )
        logger.info(f"Пост {post_id_str} успешно отправлен на модерацию")
    except Exception as e:
        logger.error(f"Ошибка при отправке на модерацию поста {post_id_str}: {e}", exc_info=True)

async def _fetch_initial_posts():
    """
    Получает последние посты из каждого паблика ВК при запуске
    """
    if not vk_clients.vk_client:
        logger.warning("VK клиент не инициализирован, пропуск начальной загрузки")
        return
    
    logger.info(f"Загружаю последние публикации из ВК групп: {config.VK_GROUP_IDS}")
    
    # Создаем множество для хранения групп с отключенной стеной
    disabled_wall_groups = set()
    
    for vk_group_id in config.VK_GROUP_IDS:
        try:
            # Получаем группу с отрицательным ID (формат для сообществ)
            group_id = -abs(vk_group_id)
            logger.info(f"Получение последней публикации для группы {vk_group_id} (ID: {group_id})")
            
            # Получаем последнюю публикацию из паблика
            posts = await vk_clients.vk_client.wall.get(
                owner_id=group_id,  # Отрицательный ID для сообщества
                count=1
            )
            
            if not posts or not posts.get('items') or len(posts['items']) == 0:
                logger.warning(f"Не удалось получить публикации из группы {vk_group_id}, ответ API: {posts}")
                continue
                
            post = posts['items'][0]
            post_id = post.get('id')
            
            # Обрабатываем пост стандартным способом (с проверкой на дубликаты)
            await _process_wall_post(
                group_id,
                post_id,
                post
            )
            
            logger.info(f"Обработка последней публикации из группы {vk_group_id} завершена")
        except Exception as e:
            error_msg = str(e)
            if "wall is disabled" in error_msg:
                logger.warning(f"У группы {vk_group_id} отключена стена, добавляю в список исключений")
                disabled_wall_groups.add(vk_group_id)
            else:
                logger.error(f"Ошибка при загрузке последней публикации из группы {vk_group_id}: {e}", exc_info=True)
    
    # Возвращаем список групп с отключенной стеной
    return disabled_wall_groups

async def _poll_vk_groups():
    """
    Периодически опрашивает стены пабликов ВК на наличие новых постов
    """
    if not vk_clients.vk_client:
        logger.warning("VK клиент не инициализирован, мониторинг не запущен")
        return

    # Словарь для отслеживания последних публикаций
    last_posts = {}
    
    # Множество для хранения групп с отключенной стеной
    disabled_wall_groups = set()
    
    while True:
        try:
            for vk_group_id in config.VK_GROUP_IDS:
                # Пропускаем группы с отключенной стеной
                if vk_group_id in disabled_wall_groups:
                    continue
                    
                group_id = -abs(vk_group_id)  # Отрицательный ID для сообщества
                
                try:
                    # Получаем последние публикации
                    posts = await vk_clients.vk_client.wall.get(
                        owner_id=group_id,
                        count=5
                    )
                    
                    if not posts.get('items'):
                        continue
                        
                    # Если это первый запрос для группы, запоминаем последний пост
                    if group_id not in last_posts:
                        last_posts[group_id] = posts['items'][0]['id']
                        continue
                    
                    # Обрабатываем только новые посты
                    new_posts = []
                    for post in posts['items']:
                        if post['id'] > last_posts[group_id]:
                            new_posts.append(post)
                    
                    # Обрабатываем и обновляем последний ID
                    if new_posts:
                        # Сортируем посты по ID (по времени) в порядке возрастания
                        new_posts.sort(key=lambda p: p['id'])
                        
                        for post in new_posts:
                            await _process_wall_post(group_id, post['id'], post)
                        
                        last_posts[group_id] = new_posts[-1]['id']
                except Exception as e:
                    error_msg = str(e)
                    if "wall is disabled" in error_msg:
                        logger.warning(f"У группы {vk_group_id} отключена стена, добавляю в список исключений")
                        disabled_wall_groups.add(vk_group_id)
                    else:
                        logger.error(f"Ошибка при получении публикаций из группы {vk_group_id}: {e}")
                
            # Пауза между проверками
            await asyncio.sleep(config.VK_POLL_INTERVAL)
        except Exception as e:
            logger.error(f"Ошибка в цикле опроса пабликов ВК: {e}")
            await asyncio.sleep(60)  # При ошибке ждем минуту перед следующей попыткой

async def start_vk_parser():
    """
    Запускает парсер для мониторинга пабликов ВК.
    """
    if not vk_clients.vk_client:
        logger.warning("VK клиент не инициализирован, парсер ВК не будет запущен")
        return
    
    if not config.VK_GROUP_IDS:
        logger.warning("Не указаны ID групп ВК для мониторинга в VK_GROUP_IDS, парсер ВК не будет запущен")
        return
    
    logger.info(f"Запускаю парсер ВК для {len(config.VK_GROUP_IDS)} групп: {config.VK_GROUP_IDS}")
    
    # Обрабатываем последние публикации при запуске и получаем группы с отключенными стенами
    disabled_wall_groups = await _fetch_initial_posts()
    
    # Запускаем регулярный опрос групп ВК с учетом групп с отключенными стенами
    asyncio.create_task(_poll_vk_groups()) 