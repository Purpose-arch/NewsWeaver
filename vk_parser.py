import asyncio
import time
from datetime import datetime, timedelta
import config
import db
import google_ai
import moderation
import vk_clients
from logger import logger

async def _process_wall_post(owner_id, post_id, post_data):
    """
    Обрабатывает полученную публикацию из паблика ВК:
    дедуплицирует, реформулирует текст и отправляет на модерацию
    """
    # Формируем уникальный идентификатор поста
    vk_post_id = f"vk_{owner_id}_{post_id}"
    
    # Проверяем, обрабатывался ли такой пост ранее
    if await db.check_processed(owner_id, post_id, source_type="vk"):
        return
    
    # Помечаем пост как обработанный для избежания дублей
    await db.mark_processed(owner_id, post_id, source_type="vk")
    
    # Извлекаем текст из поста
    text = post_data.get('text', '').strip()
    if not text:
        logger.info(f"Пропуск пустого поста {vk_post_id}")
        return
    
    # Реформулируем текст через Google AI API
    try:
        reformulated = await google_ai.reformulate_text(text)
    except Exception as e:
        logger.error(f"Ошибка реформулирования для {vk_post_id}: {e}")
        return

    # Отправляем сообщение на модерацию
    await moderation.send_for_moderation(
        owner_id, 
        post_id,
        reformulated, 
        vk_clients.vk_client, 
        post_data,
        source_type="vk"
    )

async def _fetch_initial_posts():
    """
    Получает последние посты из каждого паблика ВК при запуске
    """
    if not vk_clients.vk_client:
        logger.warning("VK клиент не инициализирован, пропуск начальной загрузки")
        return
    
    for vk_group_id in config.VK_GROUP_IDS:
        try:
            # Получаем последнюю публикацию из паблика
            posts = await vk_clients.vk_client.wall.get(
                owner_id=-abs(vk_group_id),  # Отрицательный ID для сообщества
                count=1
            )
            
            if posts.get('items') and len(posts['items']) > 0:
                post = posts['items'][0]
                await _process_wall_post(
                    -abs(vk_group_id),
                    post['id'],
                    post
                )
        except Exception as e:
            logger.error(f"Ошибка начальной загрузки для группы {vk_group_id}: {e}")

async def _poll_vk_groups():
    """
    Периодически опрашивает стены пабликов ВК на наличие новых постов
    """
    if not vk_clients.vk_client:
        logger.warning("VK клиент не инициализирован, мониторинг не запущен")
        return

    # Словарь для отслеживания последних публикаций
    last_posts = {}
    
    while True:
        try:
            for vk_group_id in config.VK_GROUP_IDS:
                group_id = -abs(vk_group_id)  # Отрицательный ID для сообщества
                
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
                
            # Пауза между проверками
            await asyncio.sleep(config.VK_POLL_INTERVAL)
        except Exception as e:
            logger.error(f"Ошибка в цикле опроса пабликов ВК: {e}")
            await asyncio.sleep(60)  # При ошибке ждем минуту перед следующей попыткой

async def start_vk_parser():
    """
    Инициализирует парсер VK: загружает историю и запускает мониторинг новых постов
    """
    # Обрабатываем прошлые публикации
    await _fetch_initial_posts()
    
    # Запускаем задачу мониторинга в отдельном таске
    if config.VK_GROUP_IDS:
        asyncio.create_task(_poll_vk_groups())
        logger.info(f"Мониторинг пабликов ВК запущен для групп: {config.VK_GROUP_IDS}")
    else:
        logger.info("Список пабликов ВК пуст, мониторинг не запущен") 