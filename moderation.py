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

# Создаем временную директорию для хранения медиафайлов на время модерации
TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

# Словарь для хранения ожидающих модерации сообщений
# Формат: {(channel_id, message_id): {данные}}
pending = {}

async def send_for_moderation(channel_id: int, message_id: int, text: str, client, original_message, source_type: str = "telegram"):
    """
    Places a news message into the in-memory moderation queue and sends it to MODERATION_CHAT_ID with accept/reject buttons.

    Args:
        channel_id: Source channel or chat ID.
        message_id: Original message ID from the source.
        text: Reformulated or checked news text.
        client: Telethon client instance that received the message.
        original_message: The original message object from the source.
        source_type: Source type ("telegram" or "vk").
    """
    key = (channel_id, message_id)

    # Проверяем, не дубликат ли это (если сообщение уже проходит модерацию)
    if key in pending:
        logger.warning(f"Message {key} already pending for moderation")
        return

    # Создаем запись в словаре pending
    pending[key] = {
        "text": text,
        "client": client,
        "message": original_message,
        "decided": None,  # None = не принято решение, "accept" или "reject"
        "moderation_msg_ids": [],  # ID сообщений в чате модерации
        "source_type": source_type,
        "media_paths": []  # Пути к временным медиафайлам
    }

    # Создаем кнопки для модерации
    buttons = [
        [
            Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
            Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}")
        ]
    ]

    # Проверяем, если есть медиа, скачиваем и отправляем вместе с текстом
    try:
        if source_type == "telegram" and hasattr(original_message, "media"):
            # В Telegram можно прислать несколько медиафайлов в одном сообщении с grouped_id
            grouped_id = getattr(original_message, 'grouped_id', None)
            
            # Создаем временную папку для этого сообщения
            message_dir = os.path.join(TEMP_MEDIA_DIR, f"tg_{channel_id}_{message_id}")
            os.makedirs(message_dir, exist_ok=True)
            
            # Сохраняем медиафайлы
            has_media = True
            media_paths = []
            
            # Если это часть альбома
            if grouped_id:
                # Получаем все сообщения из альбома
                entity = getattr(original_message, 'chat_id', None) or getattr(original_message.peer_id, 'channel_id', None)
                msgs = await client.get_messages(entity, limit=100)  # Лимит 100 для безопасности
                media_msgs = [m for m in msgs if getattr(m, 'grouped_id', None) == grouped_id]
                media_msgs.sort(key=lambda m: m.id)  # Сортируем по ID
                
                # Скачиваем каждое медиа отдельно
                for msg in media_msgs:
                    if hasattr(msg, 'media'):
                        path = await client.download_media(msg, file=message_dir)
                        if path:
                            media_paths.append(path)
            else:
                # Если это одиночное медиа
                path = await client.download_media(original_message, file=message_dir)
                if path:
                    media_paths.append(path)
                else:
                    has_media = False
            
            # Сохраняем пути к медиафайлам для последующей отправки в TargetID
            pending[key]["media_paths"] = media_paths
            
            # Отправляем в чат модерации
            if has_media and media_paths:
                if len(media_paths) > 1:
                    # Если это альбом, отправляем его без текста
                    album_msgs = await clients.bot_client.send_file(
                        config.MODERATION_CHAT_ID,
                        media_paths,
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
                        text,
                        buttons=buttons,
                        parse_mode='HTML'
                    )
                    if text_msg:
                        pending[key]["moderation_msg_ids"].append(text_msg.id)
                else:
                    # Если это одиночное медиа, отправляем с текстом
                    msg = await clients.bot_client.send_file(
                        config.MODERATION_CHAT_ID,
                        media_paths[0],
                        caption=text,
                        buttons=buttons,
                        parse_mode='HTML'
                    )
                    if msg:
                        pending[key]["moderation_msg_ids"].append(msg.id)
            else:
                # Если скачивание медиа не удалось, отправляем только текст
                msg = await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    text,
                    buttons=buttons,
                    parse_mode='HTML'
                )
                if msg:
                    pending[key]["moderation_msg_ids"].append(msg.id)
        else:
            # Если нет медиа, отправляем просто текст с кнопками
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

    logger.info(f"Sent to moderation chat {key} (source: {source_type})")

async def regenerate_with_custom_prompt(entry, custom_prompt, replied_msg_id):
    """
    Регенерирует новость с использованием кастомного промпта и отправляет в чат модерации
    """
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
        
        # Отправляем обновленный текст
        if entry.get("media_paths"):
            # Если есть медиа
            if len(entry["media_paths"]) > 1:
                # Для альбома - отправляем медиа без текста
                album_msgs = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID,
                    entry["media_paths"],
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
                    entry["media_paths"][0],
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