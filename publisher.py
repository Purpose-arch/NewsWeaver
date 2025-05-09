# publisher.py
import config
import tempfile
from logger import logger
import media
import clients
import moderation
import os
import vk_clients
from utils import markdown_to_html
import asyncio
import aiohttp
import io
import requests
from aiovk import TokenSession, API

# Глобальный VK клиент для публикации
vk_publish_client = None

async def init_vk_publish_client():
    """
    Инициализирует отдельный клиент API ВКонтакте для публикации контента
    """
    global vk_publish_client
    
    if not config.VK_PUBLISH_TOKEN:
        logger.warning("VK_PUBLISH_TOKEN не настроен в .env, публикация в ВК не будет активирована")
        return False
    
    logger.info(f"Начинаю инициализацию клиента VK API для публикации с токеном: {config.VK_PUBLISH_TOKEN[:5]}...")
    
    try:
        # Создаем асинхронную сессию с токеном
        logger.info("Создаю TokenSession для VK API публикации")
        session = TokenSession(access_token=config.VK_PUBLISH_TOKEN)
        vk_publish_client = API(session, v='5.131')  # Указываем версию API
        
        # Проверяем подключение
        logger.info("Выполняю тестовый запрос к VK API для публикации")
        if config.VK_TARGET_GROUP_ID:
            # Используем положительный ID для получения информации о группе
            positive_group_id = abs(config.VK_TARGET_GROUP_ID)
            group_info = await vk_publish_client.groups.getById(group_id=positive_group_id)
            logger.info(f"Группа для публикации {positive_group_id} доступна: {group_info}")
            return True
        else:
            logger.warning("VK_TARGET_GROUP_ID не настроен, публикация в ВК невозможна")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка инициализации VK API для публикации: {e}", exc_info=True)
        return False

async def close_vk_publish_client():
    """
    Закрывает соединение с API ВКонтакте для публикации
    """
    global vk_publish_client
    
    if vk_publish_client and hasattr(vk_publish_client, '_session') and hasattr(vk_publish_client._session, 'close'):
        try:
            await vk_publish_client._session.close()
            logger.info("VK API клиент для публикации закрыт")
        except Exception as e:
            logger.error(f"Ошибка при закрытии VK API клиента для публикации: {e}")
    else:
        logger.warning("VK API клиент для публикации не был инициализирован или уже закрыт")

async def _publish_to_vk(text, media_paths=None, vk_data=None):
    """
    Публикует сообщение в паблик ВК
    
    Args:
        text: Текст сообщения (без HTML)
        media_paths: Список путей к медиафайлам
        vk_data: Данные для публикации из ВК (если источник - ВК)
    """
    if not vk_publish_client or not config.VK_TARGET_GROUP_ID:
        logger.warning("VK клиент для публикации не инициализирован или не указан VK_TARGET_GROUP_ID, публикация в ВК пропущена")
        return False
    
    try:
        # Формируем ID группы (отрицательный для формата API ВК)
        group_id = -abs(config.VK_TARGET_GROUP_ID)
        
        # Очищаем текст от HTML-тегов для публикации в ВК
        clean_text = text.replace("<b>", "").replace("</b>", "")
        clean_text = clean_text.replace("<i>", "").replace("</i>", "")
        clean_text = clean_text.replace("<u>", "").replace("</u>", "")
        clean_text = clean_text.replace("<s>", "").replace("</s>", "")
        clean_text = clean_text.replace("<br>", "\n")
        # Очищаем гиперссылки
        import re
        clean_text = re.sub(r'<a href="[^"]+">([^<]+)</a>', r'\1', clean_text)
        
        attachments = []
        
        # Загружаем фотографии, если они есть
        if media_paths:
            for media_path in media_paths:
                try:
                    # Получаем URL сервера для загрузки фото
                    upload_url = await vk_publish_client.photos.getWallUploadServer(group_id=-group_id)
                    
                    # Читаем файл и отправляем на сервер ВК
                    with open(media_path, 'rb') as f:
                        form_data = aiohttp.FormData()
                        form_data.add_field('photo', f)
                        
                        # Используем стандартную сессию aiohttp для загрузки файла
                        async with aiohttp.ClientSession() as session:
                            async with session.post(upload_url['upload_url'], data=form_data) as response:
                                upload_data = await response.json()
                    
                    # Сохраняем загруженное фото
                    saved_photo = await vk_publish_client.photos.saveWallPhoto(
                        group_id=-group_id,
                        photo=upload_data['photo'],
                        server=upload_data['server'],
                        hash=upload_data['hash']
                    )
                    
                    # Добавляем фото в прикрепления
                    photo_id = saved_photo[0]['id']
                    owner_id = saved_photo[0]['owner_id']
                    attachments.append(f"photo{owner_id}_{photo_id}")
                    
                except Exception as e:
                    logger.error(f"Ошибка при загрузке фото в ВК: {e}")
        
        # Публикуем запись на стене
        params = {
            'owner_id': group_id,
            'message': clean_text,
            'from_group': 1  # Публикация от имени группы
        }
        
        if attachments:
            params['attachments'] = ','.join(attachments)
        
        # Отправляем запрос на публикацию
        result = await vk_publish_client.wall.post(**params)
        
        if result and 'post_id' in result:
            logger.info(f"Сообщение успешно опубликовано в ВК, post_id: {result['post_id']}")
            return True
        else:
            logger.warning(f"Странный ответ API при публикации в ВК: {result}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при публикации в ВК: {e}", exc_info=True)
        return False

async def publish(channel_id: int, message_id: int, source_type: str = "telegram"):
    """
    При «Принять» отправляет фото (если есть) с подписью (переформулированным текстом)
    в TARGET_ID, потом чистит pending.
    
    Args:
        channel_id: ID канала/паблика
        message_id: ID сообщения/поста
        source_type: Тип источника ("telegram" или "vk")
    """
    key = (channel_id, message_id)
    entry = moderation.pending.get(key)
    if not entry:
        logger.error(f"No pending entry to publish {key}")
        return

    # Переформулированные тексты уже в HTML, но проверим на наличие Markdown для совместимости
    text = markdown_to_html(entry["text"])
    # append footer link
    text = f"{text}\n\n📰 <a href=\"https://t.me/fatezhinteresting\">Фатежский Вестник</a>"
    
    # Проверяем наличие сохраненных путей к медиафайлам
    media_paths = entry.get("media_paths", [])
    telegram_success = False
    
    try:
        if media_paths:
            # Используем уже скачанные файлы
            logger.info(f"Using pre-downloaded media files for {key} (source: {source_type})")
            if len(media_paths) > 1:
                # Альбом - отправляем несколько файлов
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    media_paths,
                    caption=text,
                    parse_mode='HTML'
                )
            else:
                # Одиночное медиа
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    media_paths[0],
                    caption=text,
                    parse_mode='HTML'
                )
            telegram_success = True
        else:
            # Если по какой-то причине медиа не были скачаны заранее
            original = entry["message"]
            client = entry.get("client")
            
            if source_type == "telegram" and getattr(original, "media", None):
                # Обработка медиа из Telegram
                grouped_id = getattr(original, 'grouped_id', None)
                entity = getattr(original, 'chat_id', None) or getattr(original.peer_id, 'channel_id', None)
                with tempfile.TemporaryDirectory() as tmp:
                    if grouped_id:
                        # fetch all messages from the same album
                        msgs = await client.get_messages(entity, limit=100)
                        media_msgs = [m for m in msgs if getattr(m, 'grouped_id', None) == grouped_id]
                        media_msgs.sort(key=lambda m: m.id)
                        # Скачиваем каждое медиа отдельно
                        paths = []
                        for msg in media_msgs:
                            if getattr(msg, 'media', None):
                                path = await client.download_media(msg, file=tmp)
                                if path:
                                    paths.append(path)
                        
                        if not paths:
                            raise ValueError("Не удалось скачать медиафайлы из альбома")
                            
                        await clients.bot_client.send_file(
                            config.TARGET_ID,
                            paths,
                            caption=text,
                            parse_mode='HTML'
                        )
                        telegram_success = True
                        
                        # Сохраняем пути для публикации в ВК
                        media_paths = paths.copy()
                    else:
                        path = await client.download_media(original, file=tmp)
                        await clients.bot_client.send_file(
                            config.TARGET_ID,
                            path,
                            caption=text,
                            parse_mode='HTML'
                        )
                        telegram_success = True
                        
                        # Сохраняем путь для публикации в ВК
                        media_paths = [path]
            elif source_type == "vk" and "attachments" in original:
                # Обработка медиа из ВК, если они не были предварительно скачаны
                # Этот блок выполняется редко, так как обычно медиа уже скачаны в модерации
                with tempfile.TemporaryDirectory() as tmp:
                    
                    # Скачиваем фотографии
                    paths = []
                    for idx, attachment in enumerate(original.get("attachments", [])):
                        if attachment.get("type") == "photo":
                            # Получаем ссылку на фото
                            photo_sizes = attachment["photo"]["sizes"]
                            photo_sizes.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                            photo_url = photo_sizes[0]["url"]
                            
                            # Скачиваем фото
                            try:
                                filename = os.path.join(tmp, f"photo_{idx}.jpg")
                                response = requests.get(photo_url, stream=True)
                                if response.status_code == 200:
                                    with open(filename, 'wb') as file:
                                        for chunk in response.iter_content(chunk_size=8192):
                                            file.write(chunk)
                                    paths.append(filename)
                            except Exception as e:
                                logger.error(f"Failed to download VK photo: {e}")
                    
                    if paths:
                        if len(paths) > 1:
                            # Отправляем альбом
                            await clients.bot_client.send_file(
                                config.TARGET_ID,
                                paths,
                                caption=text,
                                parse_mode='HTML'
                            )
                        else:
                            # Отправляем одиночное фото
                            await clients.bot_client.send_file(
                                config.TARGET_ID,
                                paths[0],
                                caption=text,
                                parse_mode='HTML'
                            )
                        telegram_success = True
                        
                        # Сохраняем пути для публикации в ВК
                        media_paths = paths.copy()
                    else:
                        # Если не удалось скачать медиа, отправляем только текст
                        await clients.bot_client.send_message(
                            config.TARGET_ID,
                            text,
                            parse_mode='HTML'
                        )
                        telegram_success = True
            else:
                # Иначе просто отправляем текст
                await clients.bot_client.send_message(
                    config.TARGET_ID,
                    text,
                    parse_mode='HTML'
                )
                telegram_success = True
        
        # Публикуем в ВК после успешной публикации в Telegram
        if telegram_success and config.VK_TARGET_GROUP_ID:
            logger.info(f"Публикую сообщение в ВК {key} (source: {source_type})")
            vk_data = entry["message"] if source_type == "vk" else None
            await _publish_to_vk(text, media_paths, vk_data)
        
    except Exception as e:
        logger.error(f"Error publishing message {key} (source: {source_type}): {e}")
    finally:
        # Очищаем временные файлы
        try:
            moderation.cleanup_media_files(key)
        except Exception as e:
            logger.warning(f"Error cleaning media files: {e}")
        
        # очищаем pending и логируем
        moderation.pending.pop(key, None)
        logger.info(f"Published {key} (source: {source_type})")

async def reject(channel_id: int, message_id: int, source_type: str = "telegram"):
    """
    При «Отклонить» очищаем временные файлы и удаляем из pending.
    
    Args:
        channel_id: ID канала/паблика
        message_id: ID сообщения/поста
        source_type: Тип источника ("telegram" или "vk")
    """
    key = (channel_id, message_id)
    
    # Очищаем временные файлы перед удалением из pending
    try:
        moderation.cleanup_media_files(key)
    except Exception as e:
        logger.warning(f"Error cleaning media files: {e}")
    
    moderation.pending.pop(key, None)
    logger.info(f"Rejected {key} (source: {source_type})")