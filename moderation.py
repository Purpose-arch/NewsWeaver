# moderation.py
import asyncio
import os
import shutil
from telethon import Button, events
import config
import clients
import publisher
import media
import tempfile
from logger import logger

# Создаем временную директорию для хранения медиафайлов на время модерации
TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

# pending[(channel_id, message_id)] = {"client":…, "message":…, "text":…, "decided":…, "media_paths": […], "moderation_msg_ids": […]}
pending: dict[tuple[int,int], dict] = {}

async def send_for_moderation(channel_id: int, message_id: int, text: str, client, original_message):
    """
    Отправляет переформулированный текст и вложения в групповой чат модерации с Inline-кнопками.
    Решение фиксируется — повторные клики игнорируем.
    """
    key = (channel_id, message_id)
    pending[key] = {
        "client": client,
        "message": original_message,
        "text": text,
        "decided": False,
        "media_paths": [],  # Здесь будем хранить пути к сохраненным медиафайлам
        "moderation_msg_ids": []  # Хранение ID сообщений в чате модерации для последующего удаления
    }

    buttons = [
        [
            Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
            Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}")
        ]
    ]
    
    # Используем ID группового чата вместо отправки каждому админу
    try:
        # Отправляем медиа и текст в групповой чат модерации
        if getattr(original_message, 'media', None):
            grouped_id = getattr(original_message, 'grouped_id', None)
            entity = getattr(original_message, 'chat_id', None) or getattr(original_message.peer_id, 'channel_id', None)
            try:
                if grouped_id:
                     # Для альбомов используем загрузку и повторную отправку
                     raise ValueError("Force fallback for album handling")
                else:
                    # Пробуем отправить одиночное медиа напрямую
                    msg = await clients.bot_client.send_file(
                        config.MODERATION_CHAT_ID,
                        original_message.media,
                        caption=text,
                        parse_mode='HTML',
                        buttons=buttons
                    )
                    if msg:
                        pending[key]["moderation_msg_ids"].append(msg.id)
            except Exception as e:
                logger.warning(f"Direct send failed for moderation chat: {e}, fallback to download")
                # Создаем уникальную директорию для данного сообщения
                message_dir = os.path.join(TEMP_MEDIA_DIR, f"{channel_id}_{message_id}")
                os.makedirs(message_dir, exist_ok=True)
                
                try:
                    if grouped_id:
                        # Загружаем сообщения альбома
                        msgs = await client.get_messages(entity, limit=100)
                        media_msgs_in_group = [m for m in msgs if getattr(m, 'grouped_id', None) == grouped_id and m.media]
                        media_msgs_in_group.sort(key=lambda m: m.id)
                        
                        # Скачиваем каждое медиа отдельно и сохраняем пути
                        paths = []
                        for idx, msg in enumerate(media_msgs_in_group):
                            # Используем индекс для создания уникального имени файла
                            filename = os.path.join(message_dir, f"media_{idx}")
                            path = await client.download_media(msg, file=filename)
                            if path:
                                paths.append(path)
                        
                        if not paths:
                            raise ValueError("Не удалось скачать медиафайлы из альбома")
                        
                        # Сохраняем пути в pending для последующего использования
                        pending[key]["media_paths"] = paths

                        # Отправляем альбом БЕЗ текста новости и кнопок
                        album_msgs = await clients.bot_client.send_file(
                            config.MODERATION_CHAT_ID,
                            paths,
                            parse_mode='HTML'
                        )
                        
                        # При отправке альбома возвращается список сообщений, а не одно сообщение
                        if isinstance(album_msgs, list):
                            # Сохраняем ID всех сообщений альбома
                            for msg in album_msgs:
                                if hasattr(msg, 'id'):
                                    pending[key]["moderation_msg_ids"].append(msg.id)
                        elif hasattr(album_msgs, 'id'):
                            # На случай, если вернулось одно сообщение
                            pending[key]["moderation_msg_ids"].append(album_msgs.id)
                        
                        # Отправляем отдельно текст новости с кнопками модерации
                        text_msg = await clients.bot_client.send_message(
                            config.MODERATION_CHAT_ID,
                            text,
                            buttons=buttons,
                            parse_mode='HTML'
                        )
                        if text_msg:
                            pending[key]["moderation_msg_ids"].append(text_msg.id)
                    else:
                        # Для одиночного медиа: скачиваем и сохраняем путь
                        filename = os.path.join(message_dir, "media")
                        path = await client.download_media(original_message, file=filename)
                        
                        # Сохраняем путь в pending для последующего использования
                        pending[key]["media_paths"] = [path]
                        
                        msg = await clients.bot_client.send_file(
                            config.MODERATION_CHAT_ID,
                            path,
                            caption=text,
                            parse_mode='HTML',
                            buttons=buttons
                        )
                        if msg:
                            pending[key]["moderation_msg_ids"].append(msg.id)
                except Exception as download_send_e:
                    logger.error(f"Fallback download/send failed for moderation chat on {key}: {download_send_e}")

        else:
            # Если медиа нет, просто отправляем текст с кнопками
            msg = await clients.bot_client.send_message(
                config.MODERATION_CHAT_ID,
                text,
                buttons=buttons,
                parse_mode='HTML'
            )
            if msg:
                pending[key]["moderation_msg_ids"].append(msg.id)

    except Exception as e:
        logger.error(f"Failed to send message to moderation chat: {e}")

    logger.info(f"Sent to moderation chat {key}")
    # Планируем автоматическое отклонение через 24 часа
    asyncio.create_task(_auto_reject(key, 24 * 3600))

async def _auto_reject(key, delay: int):
    await asyncio.sleep(delay)
    entry = pending.get(key)
    if entry and not entry["decided"]:
        entry["decided"] = "reject"
        await publisher.reject(*key)
        logger.info(f"Auto-rejected {key}")

async def register_handlers():
    """
    Регистрируем CallbackQuery обработчик на бот-клиенте.
    """
    @clients.bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode()
        action, ch, mid = data.split(":")
        key = (int(ch), int(mid))
        entry = pending.get(key)

        if not entry:
            await event.answer("Срок истёк или нет данных", alert=True)
            return
        if entry["decided"]:
            await event.answer("Уже обработано", alert=True)
            return

        entry["decided"] = action
        if action == "accept":
            await publisher.publish(*key)
            await event.answer("✅ Принято", alert=False)
        else:
            await publisher.reject(*key)
            await event.answer("❌ Отклонено", alert=False)

        # Удаляем все сообщения модерации после обработки
        try:
            # Сначала пробуем удалить все сообщения по списку ID
            msg_ids = entry.get("moderation_msg_ids", [])
            logger.info(f"Attempting to delete {len(msg_ids)} moderation messages: {msg_ids}")
            
            if msg_ids:
                # Удаляем все сообщения одним запросом
                try:
                    await clients.bot_client.delete_messages(config.MODERATION_CHAT_ID, msg_ids)
                except Exception as bulk_delete_error:
                    logger.warning(f"Failed to bulk delete messages, will try one by one: {bulk_delete_error}")
                    # Если массовое удаление не удалось, пробуем удалять по одному
                    for msg_id in msg_ids:
                        try:
                            await clients.bot_client.delete_messages(config.MODERATION_CHAT_ID, msg_id)
                            await asyncio.sleep(0.2)  # небольшая задержка между удалениями
                        except Exception as msg_delete_error:
                            logger.warning(f"Cannot delete moderation message {msg_id}: {msg_delete_error}")
            
            # Отдельно пробуем удалить сообщение, на котором нажали кнопку
            # это может быть дополнительной гарантией, если оно не в списке
            if event.message and event.message.id:
                try:
                    await event.delete()
                except Exception as e:
                    logger.warning(f"Cannot delete callback message: {e}")
        except Exception as e:
            logger.warning(f"Error while deleting moderation messages: {e}")

        logger.info(f"Moderator {event.sender_id} - {action} {key}")

def cleanup_media_files(key):
    """
    Очищает скачанные медиафайлы для данного ключа
    """
    channel_id, message_id = key
    message_dir = os.path.join(TEMP_MEDIA_DIR, f"{channel_id}_{message_id}")
    if os.path.exists(message_dir):
        try:
            shutil.rmtree(message_dir)
            logger.info(f"Cleaned up media files for {key}")
        except Exception as e:
            logger.warning(f"Error cleaning up media files for {key}: {e}")