# moderation.py
import asyncio
import os
import json
import shutil
import tempfile
from telethon import Button, events
import config
import clients
import publisher
import media
import requesty
# DEPRECATED: import google_ai
import voidapi_ai
import requests
from typing import Optional, Union, List
from logger import logger
import direct_news
import pre_moderation
import vk_parser # Импортируем vk_parser для доступа к TEMP_VK_MEDIA_DIR

# Создаем временную директорию для хранения медиафайлов на время модерации
TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

# Словарь для хранения ожидающих модерации сообщений
# Формат: {(channel_id, message_id): {данные}}
pending = {}

async def send_for_moderation(channel_id: int, message_id: int, text: str, client, original_message, source_type: str = "telegram", media_paths: Optional[List[str]] = None):
    """
    Places a news message into the in-memory moderation queue and sends it to MODERATION_CHAT_ID with accept/reject buttons.

    Args:
        channel_id: Source channel or chat ID.
        message_id: Original message ID from the source.
        text: Reformulated or checked news text.
        client: Telethon client instance that received the message (can be None for VK).
        original_message: The original message object from the source (can be None for VK).
        source_type: Source type ("telegram" or "vk").
        media_paths: List of paths to temporary media files (can be None).
    """
    key = (channel_id, message_id)

    # Проверяем, не дубликат ли это (если сообщение уже проходит модерацию)
    if key in pending:
        logger.warning(f"Message {key} already pending for moderation")
        return

    # Очищаем текст перед добавлением в pending
    cleaned_text = pre_moderation.clean_blockquote_prefix(text)

    # Создаем запись в словаре pending
    pending[key] = {
        "text": cleaned_text,
        "client": client, # Can be None for VK
        "message": original_message, # Can be None for VK
        "decided": None,  # None = не принято решение, "accept" или "reject"
        "moderation_msg_ids": [],  # ID сообщений в чате модерации
        "source_type": source_type,
        "media_paths": media_paths if media_paths is not None else []  # Сохраняем переданные пути медиа
    }

    # Создаем кнопки для модерации
    buttons = [
        [
            Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
            Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}")
        ]
    ]

    # Проверяем, если есть медиа, используем пути из media_paths
    try:
        has_media = bool(pending[key]["media_paths"])
        media_to_send = pending[key]["media_paths"]

        if has_media and media_to_send:
            # Логика отправки медиа (альбом или одиночное) уже существует
            if len(media_to_send) > 1:
                # Если это альбом, отправляем его без текста (текст отдельно)
                album_msgs = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID,
                    media_to_send,
                    parse_mode='HTML'
                )

                # При отправке альбома возвращается список сообщений
                if isinstance(album_msgs, list):
                    for msg in album_msgs:
                        if hasattr(msg, 'id'):
                            pending[key]["moderation_msg_ids"].append(msg.id)
                elif hasattr(album_msgs, 'id'):
                    pending[key]["moderation_msg_ids"].append(album_msgs.id)

                # Отправляем отдельно текст с кнопками
                text_msg = await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    cleaned_text,
                    buttons=buttons,
                    parse_mode='HTML'
                )
                if text_msg: # Проверяем, что сообщение успешно отправлено и имеет ID
                     pending[key]["moderation_msg_ids"].append(text_msg.id)

            else:
                # Если это одиночное медиа, отправляем с текстом
                msg = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID,
                    media_to_send[0],
                    caption=cleaned_text,
                    buttons=buttons,
                    parse_mode='HTML'
                )
                if msg: # Проверяем, что сообщение успешно отправлено и имеет ID
                    pending[key]["moderation_msg_ids"].append(msg.id)
        else:
            # Если скачивание медиа не удалось, отправляем только текст
            msg = await clients.bot_client.send_message(
                config.MODERATION_CHAT_ID,
                cleaned_text,
                buttons=buttons,
                parse_mode='HTML'
            )
            if msg:
                pending[key]["moderation_msg_ids"].append(msg.id)

    except Exception as e:
        logger.error(f"Failed to send message to moderation chat: {e}")

    logger.info(f"Sent to moderation chat {key} (source: {source_type})")

async def regenerate_with_custom_prompt(entry, custom_prompt, replied_msg_id):
    """
    Регенерирует новость с использованием кастомного промпта и отправляет в чат модерации
    """
    # Используем пути к медиафайлам, которые уже есть в entry
    media_paths = entry.get("media_paths", [])

    try:
        # Получаем текущий текст новости и применяем кастомный промпт
        original_text = entry["text"]
        new_text = await voidapi_ai.modify_text_with_custom_prompt(original_text, custom_prompt)
        
        if not new_text:
            logger.error("Failed to regenerate text with custom prompt")
            return False
        
        # Обновляем текст в pending
        entry["text"] = new_text
        
        # Удаляем все сообщения, связанные с этой новостью в чате модерации
        try:
            # Копируем список ID сообщений, чтобы избежать проблем при изменении списка во время итерации
            msg_ids_to_delete = entry["moderation_msg_ids"].copy()
            if msg_ids_to_delete:
                logger.info(f"Deleting {len(msg_ids_to_delete)} messages from moderation chat")
                try:
                    # Пробуем удалить все сообщения одним запросом
                    await clients.bot_client.delete_messages(config.MODERATION_CHAT_ID, msg_ids_to_delete)
                except Exception as e:
                    logger.warning(f"Failed to bulk delete messages: {e}, trying one by one")
                    # Если массовое удаление не удалось, удаляем по одному
                    for msg_id in msg_ids_to_delete:
                        try:
                            await clients.bot_client.delete_messages(config.MODERATION_CHAT_ID, msg_id)
                            await asyncio.sleep(0.2)  # Небольшая задержка между удалениями
                        except Exception as msg_e:
                            logger.warning(f"Cannot delete message {msg_id}: {msg_e}")
                
                # Очищаем список ID сообщений, так как все они должны быть удалены
                entry["moderation_msg_ids"] = []
        except Exception as e:
            logger.warning(f"Error deleting moderation messages: {e}")
        
        # Создаем кнопки для новой новости
        channel_id, message_id = next((k for k, v in pending.items() if v == entry), (None, None))
        if not channel_id or not message_id:
            logger.error("Cannot find key for entry")
            return False
            
        # Определяем тип источника
        source_type = entry.get("source_type", "telegram")
        
        buttons = [
            [
                Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
                Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}")
            ]
        ]
        
        # Отправляем обновленный текст с медиа, если они есть
        if media_paths:
            # Если есть медиа
            if len(media_paths) > 1:
                # Для альбома - отправляем медиа без текста
                album_msgs = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID,
                    media_paths,
                    parse_mode='HTML'
                )
                
                # При отправке альбома возвращается список сообщений
                if isinstance(album_msgs, list):
                    for msg in album_msgs:
                        if hasattr(msg, 'id'):
                            entry["moderation_msg_ids"].append(msg.id)
                elif hasattr(album_msgs, 'id'):
                    entry["moderation_msg_ids"].append(album_msgs.id)
                
                # Отправляем отдельно текст с кнопками
                text_msg = await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    new_text,
                    buttons=buttons,
                    parse_mode='HTML'
                )
                if text_msg:
                    entry["moderation_msg_ids"].append(text_msg.id)
            else:
                # Для одиночного файла
                msg = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID,
                    media_paths[0],
                    caption=new_text,
                    parse_mode='HTML',
                    buttons=buttons
                )
                if msg:
                    entry["moderation_msg_ids"].append(msg.id)
        else:
            # Если медиа нет
            msg = await clients.bot_client.send_message(
                config.MODERATION_CHAT_ID,
                new_text,
                buttons=buttons,
                parse_mode='HTML'
            )
            if msg:
                entry["moderation_msg_ids"].append(msg.id)
                
        logger.info(f"Regenerated news with custom prompt for {channel_id}:{message_id} (source: {source_type})")
        return True
    except Exception as e:
        logger.error(f"Error regenerating with custom prompt: {e}")
        return False

async def register_handlers():
    """
    Регистрируем CallbackQuery обработчик на бот-клиенте.
    """
    @clients.bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode()
        
        # Проверяем, не является ли это запросом для прямой новости
        if data.startswith("direct_"):
            # Делегируем обработку модулю direct_news
            if await direct_news.process_direct_callback(event):
                return
        
        # Обработка обычных переформулированных новостей
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
            await publisher.publish(*key, entry.get("source_type", "telegram"))
            await event.answer("✅ Принято", alert=False)
        else:
            await publisher.reject(*key, entry.get("source_type", "telegram"))
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
            try:
                # Проверяем, есть ли у event доступ к message (может отсутствовать)
                if hasattr(event, 'message') and event.message and event.message.id:
                    await event.delete()
            except Exception as e:
                logger.warning(f"Error while deleting moderation messages: {e}")
        except Exception as e:
            logger.warning(f"Error while deleting moderation messages: {e}")

        logger.info(f"Moderator {event.sender_id} - {action} {key} (source: {entry.get('source_type', 'telegram')})")

        # После обработки новости, очищаем временные медиафайлы
        cleanup_media_files(key)

    # Регистрируем обработчик ответов на сообщения для кастомных промптов
    @clients.bot_client.on(events.NewMessage(chats=config.MODERATION_CHAT_ID, func=lambda e: e.is_reply))
    async def custom_prompt_handler(event):
        try:
            # Получаем сообщение, на которое был ответ
            replied_msg = await event.get_reply_message()
            if not replied_msg:
                return
                
            # Проверяем, что ответ был на сообщение с новостью на модерации
            # Для этого ищем ID сообщения в списках moderation_msg_ids во всех pending
            msg_id = replied_msg.id
            found_entry = None
            found_key = None
            
            for key, entry in pending.items():
                if msg_id in entry.get("moderation_msg_ids", []) and not entry["decided"]:
                    found_entry = entry
                    found_key = key
                    break
                    
            if not found_entry:
                # Если не нашли, значит ответ не на новость на модерации
                return
                
            # Получаем текст ответа - это кастомный промпт
            custom_prompt = event.text.strip()
            if not custom_prompt:
                return
                
            # Удаляем сообщение с кастомным промптом, чтобы не засорять чат
            try:
                await event.delete()
            except Exception as e:
                logger.warning(f"Cannot delete custom prompt message: {e}")
                
            # Регенерируем новость с кастомным промптом
            channel_id, message_id = found_key
            logger.info(f"Regenerating news {channel_id}:{message_id} with custom prompt: {custom_prompt}")
            
            success = await regenerate_with_custom_prompt(found_entry, custom_prompt, replied_msg.id)
            if not success:
                # Если не удалось регенерировать, отправляем сообщение об ошибке
                await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    f"❌ Не удалось регенерировать новость с промптом:\n<code>{custom_prompt}</code>",
                    parse_mode='HTML',
                    reply_to=replied_msg.id
                )
                
        except Exception as e:
            logger.error(f"Error in custom prompt handler: {e}")

    # Регистрируем обработчики из модуля direct_news
    await direct_news.register_handlers()

def cleanup_media_files(key):
    """
    Очищает скачанные медиафайлы для данного ключа.
    Удаляет временные файлы и их родительскую директорию.
    """
    entry = pending.get(key)
    if not entry:
        logger.warning(f"No pending entry found for key {key} during cleanup.")
        return

    media_paths = entry.get("media_paths", [])
    if not media_paths:
        # logger.debug(f"No media paths found for key {key} to cleanup.") # Too noisy
        return

    logger.info(f"Cleaning up {len(media_paths)} media files for {key}...")

    # Attempt to remove each file and its parent directory
    # We assume all media for one message are in the same temp directory
    cleaned_dirs = set() # To avoid attempting to remove the same directory multiple times

    for file_path in media_paths:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Removed file: {file_path}")
                parent_dir = os.path.dirname(file_path)
                if parent_dir not in cleaned_dirs:
                    # Try to remove the parent directory, but only if it's empty
                    # and is within our known temporary media dirs
                    if parent_dir.startswith(tempfile.gettempdir()) and parent_dir != tempfile.gettempdir(): # Basic check to stay within temp dir
                         try:
                            # Use rmtree on the parent directory
                            shutil.rmtree(parent_dir)
                            logger.debug(f"Removed parent directory: {parent_dir}")
                            cleaned_dirs.add(parent_dir)
                         except OSError as e: # rmtree might fail if dir is not empty (e.g., due to other files/errors)
                             logger.warning(f"Could not remove parent directory {parent_dir}: {e}")
                         except Exception as e:
                              logger.warning(f"Unexpected error removing directory {parent_dir}: {e}")
                    else:
                         logger.warning(f"Skipping removal of parent directory {parent_dir} outside of temp dir or is root temp dir.")
            except OSError as e:
                logger.warning(f"Could not remove file {file_path}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error removing file {file_path}: {e}")
        else:
            logger.debug(f"File not found for cleanup: {file_path}")

    # Remove the entry from pending after cleanup attempt
    # This should happen regardless of cleanup success to prevent memory leak
    if key in pending:
        del pending[key]
        logger.info(f"Removed pending entry for {key}.")