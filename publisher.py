# publisher.py
import config
import tempfile
from logger import logger
import media
import clients
import moderation
import os
from utils import markdown_to_html
import asyncio
import aiohttp
import io
import requests
import fast_file_transfer

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
    
    # Подготавливаем текст для Telegram с HTML-форматированной ссылкой
    telegram_text = f"{text}\n\n📰 <a href=\"https://t.me/fatezhinteresting\">Фатежский Вестник</a>"
    
    # Проверяем наличие сохраненных путей к медиафайлам
    media_paths = entry.get("media_paths", [])
    
    logger.info(f"Публикую новость {key} (source: {source_type}), медиафайлов: {len(media_paths)}")
    if media_paths:
        logger.info(f"Пути к медиафайлам: {media_paths}")
        # Проверяем существование каждого файла
        for path in media_paths:
            if os.path.exists(path):
                size = os.path.getsize(path)
                logger.info(f"Файл существует: {path} (размер: {size} байт)")
            else:
                logger.error(f"Файл не существует: {path}")
    
    telegram_success = False
    
    try:
        if media_paths:
            # Фильтруем только существующие файлы
            existing_media_paths = [path for path in media_paths if os.path.exists(path)]
            logger.info(f"Существующих медиафайлов: {len(existing_media_paths)}/{len(media_paths)}")
            
            # Используем уже скачанные файлы, если они существуют
            if existing_media_paths:
                logger.info(f"Using pre-downloaded media files for {key} (source: {source_type})")
                if len(existing_media_paths) > 1:
                    # Альбом - отправляем несколько файлов
                    logger.info(f"Отправляю альбом из {len(existing_media_paths)} файлов в Telegram")
                    await clients.bot_client.send_file(
                        config.TARGET_ID,
                        existing_media_paths,
                        caption=telegram_text,
                        parse_mode='HTML'
                    )
                else:
                    # Одиночное медиа
                    logger.info(f"Отправляю одиночное медиа в Telegram: {existing_media_paths[0]}")
                    await clients.bot_client.send_file(
                        config.TARGET_ID,
                        existing_media_paths[0],
                        caption=telegram_text,
                        parse_mode='HTML'
                    )
                telegram_success = True
                # Обновляем список media_paths 
                media_paths = existing_media_paths
            else:
                logger.warning(f"Все предварительно скачанные медиафайлы недоступны, пытаюсь скачать заново")
                # Далее идет код для повторной загрузки, который уже существует
        
            # Если все предварительно скачанные файлы недоступны или их не было, продолжаем с оригинальным кодом
            if not telegram_success:
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
                                    path = fast_file_transfer.download_file(client, msg.document, tmp)
                                    if path:
                                        paths.append(path)
                        
                            if not paths:
                                raise ValueError("Не удалось скачать медиафайлы из альбома")
                            
                            await clients.bot_client.send_file(
                                config.TARGET_ID,
                                paths,
                                caption=telegram_text,
                                parse_mode='HTML'
                            )
                            telegram_success = True
                            
                            # Сохраняем пути 
                            media_paths = paths.copy()
                        else:
                            path = fast_file_transfer.download_file(client, original, tmp)
                            await clients.bot_client.send_file(
                                config.TARGET_ID,
                                path,
                                caption=telegram_text,
                                parse_mode='HTML'
                            )
                            telegram_success = True
                            
                            # Сохраняем путь 
                            media_paths = [path]
                else:
                    # Иначе просто отправляем текст
                    logger.info(f"Отправляю только текст в Telegram (нет медиафайлов)")
                    await clients.bot_client.send_message(
                        config.TARGET_ID,
                        telegram_text,
                        parse_mode='HTML'
                    )
                    telegram_success = True
        else:
            # Если вообще нет медиафайлов, отправляем только текст
            logger.info(f"Отправляю только текст в Telegram (нет медиафайлов совсем)")
            await clients.bot_client.send_message(
                config.TARGET_ID,
                telegram_text,
                parse_mode='HTML'
            )
            telegram_success = True
        
    except Exception as e:
        logger.error(f"Error publishing message {key} (source: {source_type}): {e}", exc_info=True)
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