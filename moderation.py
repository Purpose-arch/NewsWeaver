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
import direct_news
import requesty
import google_ai
import requests
from typing import Optional, Union, List

# Создаем временную директорию для хранения медиафайлов на время модерации
TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

# pending[(channel_id, message_id)] = {"client":…, "message":…, "text":…, "decided":…, "media_paths": […], "moderation_msg_ids": […]}
pending: dict[tuple[int,int], dict] = {}

async def send_for_moderation(channel_id: int, message_id: int, text: str, client, original_message, source_type: str = "telegram"):
    """
    Отправляет переформулированный текст и вложения в групповой чат модерации с Inline-кнопками.
    Решение фиксируется — повторные клики игнорируем.
    
    Args:
        channel_id: ID канала или группы
        message_id: ID сообщения или поста
        text: Переформулированный текст для модерации
        client: Клиент API (Telegram или ВК)
        original_message: Исходное сообщение/пост
        source_type: Тип источника ("telegram" или "vk")
    """
    key = (channel_id, message_id)
    pending[key] = {
        "client": client,
        "message": original_message,
        "text": text,
        "decided": False,
        "media_paths": [],  # Здесь будем хранить пути к сохраненным медиафайлам
        "moderation_msg_ids": [],  # Хранение ID сообщений в чате модерации для последующего удаления
        "source_type": source_type  # Сохраняем тип источника для последующей обработки
    }

    buttons = [
        [
            Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}:{source_type}"),
            Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}:{source_type}")
        ]
    ]
    
    # Используем ID группового чата вместо отправки каждому админу
    try:
        # Разная обработка для Telegram и VK
        if source_type == "telegram":
            # Отправляем медиа и текст из Telegram в групповой чат модерации
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
        
        elif source_type == "vk":
            # Обработка медиафайлов из ВК
            message_dir = os.path.join(TEMP_MEDIA_DIR, f"vk_{channel_id}_{message_id}")
            os.makedirs(message_dir, exist_ok=True)
            
            has_media = False
            media_paths = []
            
            # Проверяем наличие фотографий в посте
            if "attachments" in original_message:
                for attachment in original_message.get("attachments", []):
                    if attachment.get("type") == "photo":
                        has_media = True
                        # Получаем ссылку на самую большую версию фото
                        photo_sizes = attachment["photo"]["sizes"]
                        photo_sizes.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                        photo_url = photo_sizes[0]["url"]
                        
                        # Скачиваем фото
                        try:
                            filename = os.path.join(message_dir, f"photo_{len(media_paths)}.jpg")
                            response = requests.get(photo_url, stream=True)
                            if response.status_code == 200:
                                with open(filename, 'wb') as file:
                                    for chunk in response.iter_content(chunk_size=8192):
                                        file.write(chunk)
                                media_paths.append(filename)
                        except Exception as e:
                            logger.error(f"Failed to download VK photo: {e}")
            
            # Сохраняем пути к скачанным медиафайлам
            pending[key]["media_paths"] = media_paths
            
            if has_media and media_paths:
                if len(media_paths) > 1:
                    # Отправляем медиа альбомом
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
                    
                    # Отправляем отдельно текст новости с кнопками модерации
                    text_msg = await clients.bot_client.send_message(
                        config.MODERATION_CHAT_ID,
                        f"<b>Источник: ВК (группа {channel_id})</b>\n\n{text}",
                        buttons=buttons,
                        parse_mode='HTML'
                    )
                    if text_msg:
                        pending[key]["moderation_msg_ids"].append(text_msg.id)
                else:
                    # Отправляем одиночное медиа с текстом
                    msg = await clients.bot_client.send_file(
                        config.MODERATION_CHAT_ID,
                        media_paths[0],
                        caption=f"<b>Источник: ВК (группа {channel_id})</b>\n\n{text}",
                        parse_mode='HTML',
                        buttons=buttons
                    )
                    if msg:
                        pending[key]["moderation_msg_ids"].append(msg.id)
            else:
                # Если медиа нет, просто отправляем текст с кнопками
                msg = await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    f"<b>Источник: ВК (группа {channel_id})</b>\n\n{text}",
                    buttons=buttons,
                    parse_mode='HTML'
                )
                if msg:
                    pending[key]["moderation_msg_ids"].append(msg.id)

    except Exception as e:
        logger.error(f"Failed to send message to moderation chat: {e}")

    logger.info(f"Sent to moderation chat {key} (source: {source_type})")
    # Планируем автоматическое отклонение через 24 часа
    asyncio.create_task(_auto_reject(key, 24 * 3600))

async def _auto_reject(key, delay: int):
    await asyncio.sleep(delay)
    entry = pending.get(key)
    if entry and not entry["decided"]:
        entry["decided"] = "reject"
        source_type = entry.get("source_type", "telegram")
        await publisher.reject(*key, source_type)
        logger.info(f"Auto-rejected {key} (source: {source_type})")

async def regenerate_with_custom_prompt(entry, custom_prompt, replied_msg_id):
    """
    Регенерирует новость с использованием кастомного промпта и отправляет в чат модерации
    """
    try:
        # Получаем текущий текст новости и применяем кастомный промпт
        original_text = entry["text"]
        new_text = await google_ai.modify_text_with_custom_prompt(original_text, custom_prompt)
        
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
                Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}:{source_type}"),
                Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}:{source_type}")
            ]
        ]
        
        # Добавляем префикс для VK, если нужно
        prefix = ""
        if source_type == "vk":
            prefix = f"<b>Источник: ВК (группа {channel_id})</b>\n\n"
        
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
                    prefix + new_text,
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
                    caption=prefix + new_text,
                    parse_mode='HTML',
                    buttons=buttons
                )
                if msg:
                    entry["moderation_msg_ids"].append(msg.id)
        else:
            # Если медиа нет
            msg = await clients.bot_client.send_message(
                config.MODERATION_CHAT_ID,
                prefix + new_text,
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
        action, ch, mid, source_type = data.split(":")
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
            await publisher.publish(*key, source_type)
            await event.answer("✅ Принято", alert=False)
        else:
            await publisher.reject(*key, source_type)
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

        logger.info(f"Moderator {event.sender_id} - {action} {key} (source: {source_type})")

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