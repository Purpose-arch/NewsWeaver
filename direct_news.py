# direct_news.py
import asyncio
import os
import shutil
from telethon import Button, events
import config
import clients
import tempfile
from logger import logger
from utils import markdown_to_html
import publisher

# Создаем временную директорию для хранения медиафайлов на время модерации
TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media_direct")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

# direct_news[message_id] = {"message": …, "text": …, "decided": …, "media_paths": [], "moderation_msg_ids": [], "reply_to_id": …}
direct_news: dict[int, dict] = {}

# Словарь для отслеживания альбомов: grouped_id -> message_id первого сообщения альбома
album_tracking: dict[int, int] = {}

# Переменная для хранения ID бота, заполняется при инициализации
BOT_ID = None

async def process_direct_message(message):
    """
    Обрабатывает прямые сообщения от админов в чате модерации.
    Отвечает на сообщение с вопросом об отправке и кнопками модерации.
    """
    global BOT_ID
    
    # Получаем ID бота, если ещё не получали
    if BOT_ID is None:
        try:
            me = await clients.bot_client.get_me()
            BOT_ID = me.id
            logger.info(f"Bot ID initialized: {BOT_ID}")
        except Exception as e:
            logger.error(f"Failed to get bot ID: {e}")
            return
    
    # Игнорируем сообщения от бота
    if message.sender_id == BOT_ID:
        return
    
    # Игнорируем сообщения, которые сами являются ответами
    if message.reply_to is not None:
        return
    
    # Получаем текст сообщения
    text = message.text or message.message or ""
    
    # Проверяем, является ли сообщение частью альбома
    grouped_id = getattr(message, 'grouped_id', None)
    
    # Проверяем, есть ли уже обрабатываемый альбом с таким grouped_id
    if grouped_id and grouped_id in album_tracking:
        # Это сообщение из уже обрабатываемого альбома, добавляем его медиа к существующей записи
        first_message_id = album_tracking[grouped_id]
        if first_message_id in direct_news and message.media:
            logger.info(f"Добавляю медиа из сообщения {message.id} к альбому {grouped_id} (первое сообщение {first_message_id})")
            
            # Создаем директорию для этого сообщения, если еще не создана
            message_dir = os.path.join(TEMP_MEDIA_DIR, f"direct_{first_message_id}")
            os.makedirs(message_dir, exist_ok=True)
            
            # Скачиваем медиа
            try:
                idx = len(direct_news[first_message_id]["media_paths"])
                filename = os.path.join(message_dir, f"media_{idx}")
                path = await clients.bot_client.download_media(message, file=filename)
                if path:
                    logger.info(f"Медиа из альбома сохранено по пути: {path}")
                    direct_news[first_message_id]["media_paths"].append(path)
                
                # Если в этом сообщении есть текст и он не пустой, добавим его к основному тексту
                if text:
                    if direct_news[first_message_id]["text"]:
                        direct_news[first_message_id]["text"] += f"\n\n{text}"
                    else:
                        direct_news[first_message_id]["text"] = text
            except Exception as e:
                logger.error(f"Error downloading media from album message {message.id}: {e}", exc_info=True)
        
        # Не продолжаем обработку отдельных сообщений альбома
        return
    
    # Создаем уникальный идентификатор для сообщения
    message_id = message.id
    
    # Проверяем, что сообщение еще не обрабатывалось
    if message_id in direct_news:
        return
    
    # Создаем временную директорию для хранения медиа, если есть
    media_paths = []
    if message.media:
        logger.info(f"Прямое сообщение {message_id} содержит медиа")
        try:
            # Создаем директорию для этого сообщения
            message_dir = os.path.join(TEMP_MEDIA_DIR, f"direct_{message_id}")
            os.makedirs(message_dir, exist_ok=True)
            
            if grouped_id:
                # Это первое обрабатываемое сообщение из альбома
                logger.info(f"Сообщение {message_id} является первым в альбоме с grouped_id={grouped_id}")
                
                # Регистрируем альбом в системе отслеживания
                album_tracking[grouped_id] = message_id
                
                # Обрабатываем только текущее сообщение альбома, так как боты не могут использовать get_messages
                # для получения истории сообщений
                filename = os.path.join(message_dir, "media_0")
                path = await clients.bot_client.download_media(message, file=filename)
                if path:
                    logger.info(f"Медиа из альбома сохранено по пути: {path}")
                    media_paths.append(path)
                
                logger.info(f"Загружено первое медиа из альбома. Остальные медиа будут обработаны отдельно.")
            else:
                # Одиночное медиа
                logger.info(f"Сообщение {message_id} содержит одиночное медиа")
                filename = os.path.join(message_dir, "media")
                path = await clients.bot_client.download_media(message, file=filename)
                if path:
                    logger.info(f"Медиа сохранено по пути: {path}")
                    media_paths.append(path)
        except Exception as e:
            logger.error(f"Error downloading media from direct message {message_id}: {e}", exc_info=True)
    
    # Пропускаем пустые сообщения без медиа
    if not text and not media_paths:
        logger.info(f"Игнорирую пустое сообщение без медиа: {message_id}")
        return
    
    # Создаем кнопки для модерации
    buttons = [
        [
            Button.inline("✅ Отправить", f"direct_accept:{message_id}"),
            Button.inline("❌ Отменить", f"direct_reject:{message_id}")
        ]
    ]
    
    # Отправляем ответ с вопросом и кнопками
    try:
        reply_msg = await clients.bot_client.send_message(
            config.MODERATION_CHAT_ID,
            "Отправить это сообщение в канал?",
            reply_to=message_id,
            buttons=buttons
        )
        
        # Сохраняем информацию о сообщении
        direct_news[message_id] = {
            "message": message,
            "text": text,
            "decided": False,
            "media_paths": media_paths,
            "moderation_msg_ids": [reply_msg.id],
            "reply_to_id": message_id
        }
        
        if media_paths:
            logger.info(f"Added direct message {message_id} for moderation with {len(media_paths)} media files: {media_paths}")
        else:
            logger.info(f"Added direct message {message_id} for moderation (text only)")
        
        # Планируем автоматическое отклонение через 24 часа
        asyncio.create_task(_auto_reject_direct(message_id, 24 * 3600))
    except Exception as e:
        logger.error(f"Failed to process direct message {message_id}: {e}", exc_info=True)
        # Очищаем скачанные файлы в случае ошибки
        cleanup_media_files_direct(message_id)
        
        # Удаляем запись из отслеживания альбомов, если это был альбом
        if grouped_id and grouped_id in album_tracking and album_tracking[grouped_id] == message_id:
            del album_tracking[grouped_id]

async def _auto_reject_direct(message_id, delay: int):
    """
    Автоматически отклоняет прямую новость через указанное время.
    """
    await asyncio.sleep(delay)
    entry = direct_news.get(message_id)
    if entry and not entry["decided"]:
        entry["decided"] = "reject"
        await reject_direct_news(message_id)
        logger.info(f"Auto-rejected direct message {message_id}")
        
        # Очищаем запись из отслеживания альбомов
        for grouped_id, msg_id in list(album_tracking.items()):
            if msg_id == message_id:
                del album_tracking[grouped_id]
                break

async def process_direct_callback(event):
    """
    Обрабатывает нажатия на кнопки для прямых новостей.
    """
    data = event.data.decode()
    action, message_id = data.split(":")
    message_id = int(message_id)
    entry = direct_news.get(message_id)
    
    if not entry:
        await event.answer("Срок истёк или нет данных", alert=True)
        return True  # Обработали событие
    if entry["decided"]:
        await event.answer("Уже обработано", alert=True)
        return True  # Обработали событие
    
    entry["decided"] = action
    if action == "direct_accept":
        await publish_direct_news(message_id)
        await event.answer("✅ Отправлено", alert=False)
    else:
        await reject_direct_news(message_id)
        await event.answer("❌ Отменено", alert=False)
    
    # Удаляем сообщение с кнопками модерации
    try:
        await event.delete()
    except Exception as e:
        logger.warning(f"Cannot delete direct moderation message: {e}")
        
    logger.info(f"Admin {event.sender_id} - {action} for direct message {message_id}")
    
    # Очищаем запись из отслеживания альбомов
    for grouped_id, msg_id in list(album_tracking.items()):
        if msg_id == message_id:
            del album_tracking[grouped_id]
            break
            
    return True  # Обработали событие

async def publish_direct_news(message_id: int):
    """
    Публикует прямую новость от админа в целевой канал.
    """
    entry = direct_news.get(message_id)
    if not entry:
        logger.error(f"No direct news entry to publish {message_id}")
        return
    
    # Конвертируем markdown в HTML
    text = markdown_to_html(entry["text"])
    
    # Добавляем подпись канала для Telegram (HTML формат)
    telegram_text = text
    if telegram_text:
        telegram_text = f"{telegram_text}\n\n📰 <a href=\"https://t.me/fatezhinteresting\">Фатежский Вестник</a>"
    else:
        telegram_text = "📰 <a href=\"https://t.me/fatezhinteresting\">Фатежский Вестник</a>"
    
    telegram_success = False
    media_paths = entry.get("media_paths", [])
    
    logger.info(f"Публикую прямую новость {message_id}, медиафайлов: {len(media_paths)}")
    if media_paths:
        logger.info(f"Пути к медиафайлам: {media_paths}")
        # Проверяем существование каждого файла
        for path in media_paths:
            if os.path.exists(path):
                size = os.path.getsize(path)
                logger.info(f"Файл существует: {path} (размер: {size} байт)")
            else:
                logger.error(f"Файл не существует: {path}")
    
    try:
        # Если есть медиафайлы, отправляем их вместе с текстом
        if media_paths:
            # Фильтруем только существующие файлы
            existing_media_paths = [path for path in media_paths if os.path.exists(path)]
            logger.info(f"Существующих медиафайлов: {len(existing_media_paths)}/{len(media_paths)}")
            
            if len(existing_media_paths) > 1:
                # Альбом
                logger.info(f"Отправляю альбом из {len(existing_media_paths)} файлов в Telegram")
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    existing_media_paths,
                    caption=telegram_text,
                    parse_mode='HTML'
                )
            elif len(existing_media_paths) == 1:
                # Одиночное медиа
                logger.info(f"Отправляю одиночное медиа в Telegram: {existing_media_paths[0]}")
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    existing_media_paths[0],
                    caption=telegram_text,
                    parse_mode='HTML'
                )
            else:
                # Нет существующих файлов, отправляем только текст
                logger.warning("Все медиафайлы недоступны, отправляю только текст")
                await clients.bot_client.send_message(
                    config.TARGET_ID,
                    telegram_text,
                    parse_mode='HTML'
                )
        else:
            # Только текст
            logger.info(f"Отправляю только текст в Telegram (нет медиафайлов)")
            await clients.bot_client.send_message(
                config.TARGET_ID,
                telegram_text,
                parse_mode='HTML'
            )
            
        telegram_success = True
        logger.info(f"Published direct news {message_id} to Telegram")
        
    except Exception as e:
        logger.error(f"Error publishing direct news {message_id}: {e}", exc_info=True)
    finally:
        # Очищаем временные файлы
        cleanup_media_files_direct(message_id)
        # Удаляем запись из словаря
        direct_news.pop(message_id, None)

async def reject_direct_news(message_id: int):
    """
    Отклоняет публикацию прямой новости от админа.
    """
    # Очищаем временные файлы
    cleanup_media_files_direct(message_id)
    # Удаляем запись из словаря
    direct_news.pop(message_id, None)
    logger.info(f"Rejected direct news {message_id}")

def cleanup_media_files_direct(message_id):
    """
    Очищает скачанные медиафайлы для прямой новости
    """
    message_dir = os.path.join(TEMP_MEDIA_DIR, f"direct_{message_id}")
    if os.path.exists(message_dir):
        try:
            shutil.rmtree(message_dir)
            logger.info(f"Cleaned up media files for direct news {message_id}")
        except Exception as e:
            logger.warning(f"Error cleaning up media files for direct news {message_id}: {e}")

async def register_handlers():
    """
    Регистрирует обработчик сообщений для прямых новостей.
    """
    # Регистрируем обработчик сообщений для чата модерации
    @clients.bot_client.on(events.NewMessage(chats=config.MODERATION_CHAT_ID))
    async def new_message_handler(event):
        await process_direct_message(event.message) 