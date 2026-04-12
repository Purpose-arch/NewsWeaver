# direct_news.py
import asyncio
import os
import shutil
from telethon import Button, events
import src.core.config as config
import src.core.clients as clients
import tempfile
from src.core.logger import logger
from src.utils.utils import markdown_to_html
import src.features.publisher as publisher

TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media_direct")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

# direct_news[message_id] = {"message": …, "text": …, "decided": …, "media_paths": [], "moderation_msg_ids": [], "reply_to_id": …}
direct_news: dict[int, dict] = {}

album_tracking: dict[int, int] = {}

BOT_ID = None


async def process_direct_message(message):
    """
    Processes direct messages from admins in the moderation chat.
    Replies with a confirmation message and moderation buttons.
    """
    global BOT_ID

    if BOT_ID is None:
        try:
            me = await clients.bot_client.get_me()
            BOT_ID = me.id
            logger.info(f"Bot ID initialized: {BOT_ID}")
        except Exception as e:
            logger.error(f"Failed to get bot ID: {e}")
            return

    if message.sender_id == BOT_ID:
        return

    if message.reply_to is not None:
        return

    text = message.text or message.message or ""

    grouped_id = getattr(message, "grouped_id", None)

    if grouped_id and grouped_id in album_tracking:
        first_message_id = album_tracking[grouped_id]
        if first_message_id in direct_news and message.media:
            logger.info(
                f"Добавляю медиа из сообщения {message.id} к альбому {grouped_id} (первое сообщение {first_message_id})"
            )

            message_dir = os.path.join(TEMP_MEDIA_DIR, f"direct_{first_message_id}")
            os.makedirs(message_dir, exist_ok=True)

            try:
                idx = len(direct_news[first_message_id]["media_paths"])
                filename = os.path.join(message_dir, f"media_{idx}")
                path = await clients.bot_client.download_media(message, file=filename)
                if path:
                    logger.info(f"Медиа из альбома сохранено по пути: {path}")
                    direct_news[first_message_id]["media_paths"].append(path)

                if text:
                    if direct_news[first_message_id]["text"]:
                        direct_news[first_message_id]["text"] += f"\n\n{text}"
                    else:
                        direct_news[first_message_id]["text"] = text
            except Exception as e:
                logger.error(
                    f"Error downloading media from album message {message.id}: {e}",
                    exc_info=True,
                )

        return

    message_id = message.id

    if message_id in direct_news:
        return

    media_paths = []
    if message.media:
        logger.info(f"Прямое сообщение {message_id} содержит медиа")
        try:
            message_dir = os.path.join(TEMP_MEDIA_DIR, f"direct_{message_id}")
            os.makedirs(message_dir, exist_ok=True)

            if grouped_id:
                logger.info(
                    f"Сообщение {message_id} является первым в альбоме с grouped_id={grouped_id}"
                )

                album_tracking[grouped_id] = message_id

                filename = os.path.join(message_dir, "media_0")
                path = await clients.bot_client.download_media(message, file=filename)
                if path:
                    logger.info(f"Медиа из альбома сохранено по пути: {path}")
                    media_paths.append(path)

                logger.info(
                    f"Загружено первое медиа из альбома. Остальные медиа будут обработаны отдельно."
                )
            else:
                logger.info(f"Сообщение {message_id} содержит одиночное медиа")
                filename = os.path.join(message_dir, "media")
                path = await clients.bot_client.download_media(message, file=filename)
                if path:
                    logger.info(f"Медиа сохранено по пути: {path}")
                    media_paths.append(path)
        except Exception as e:
            logger.error(
                f"Error downloading media from direct message {message_id}: {e}",
                exc_info=True,
            )

    if not text and not media_paths:
        logger.info(f"Игнорирую пустое сообщение без медиа: {message_id}")
        return

    buttons = [
        [
            Button.inline("✅ Отправить", f"direct_accept:{message_id}"),
            Button.inline("❌ Отменить", f"direct_reject:{message_id}"),
        ]
    ]

    try:
        reply_msg = await clients.bot_client.send_message(
            config.MODERATION_CHAT_ID,
            "Отправить это сообщение в канал?",
            reply_to=message_id,
            buttons=buttons,
        )

        direct_news[message_id] = {
            "message": message,
            "text": text,
            "decided": False,
            "media_paths": media_paths,
            "moderation_msg_ids": [reply_msg.id],
            "reply_to_id": message_id,
        }

        if media_paths:
            logger.info(
                f"Added direct message {message_id} for moderation with {len(media_paths)} media files: {media_paths}"
            )
        else:
            logger.info(f"Added direct message {message_id} for moderation (text only)")
    except Exception as e:
        logger.error(
            f"Failed to process direct message {message_id}: {e}", exc_info=True
        )
        cleanup_media_files_direct(message_id)

        if (
            grouped_id
            and grouped_id in album_tracking
            and album_tracking[grouped_id] == message_id
        ):
            del album_tracking[grouped_id]


async def process_direct_callback(event):
    """
    Handles inline button callbacks for direct news.
    """
    data = event.data.decode()
    action, message_id = data.split(":")
    message_id = int(message_id)
    entry = direct_news.get(message_id)

    if not entry:
        await event.answer("Срок истёк или нет данных", alert=True)
        return True
    if entry["decided"]:
        await event.answer("Уже обработано", alert=True)
        return True

    entry["decided"] = action
    if action == "direct_accept":
        await publish_direct_news(message_id)
        await event.answer("✅ Отправлено", alert=False)
    else:
        await reject_direct_news(message_id)
        await event.answer("❌ Отменено", alert=False)

    try:
        await event.delete()
    except Exception as e:
        logger.warning(f"Cannot delete direct moderation message: {e}")

    logger.info(f"Admin {event.sender_id} - {action} for direct message {message_id}")

    for grouped_id, msg_id in list(album_tracking.items()):
        if msg_id == message_id:
            del album_tracking[grouped_id]
            break

    return True


async def publish_direct_news(message_id: int):
    """
    Publishes the direct news from an admin to the target channel.
    """
    entry = direct_news.get(message_id)
    if not entry:
        logger.error(f"No direct news entry to publish {message_id}")
        return

    text = markdown_to_html(entry["text"])

    telegram_text = text
    if telegram_text:
        telegram_text = f'{telegram_text}\n\n📰 <a href="https://t.me/your_channel">Название вашего канала</a>'
    else:
        telegram_text = (
            '📰 <a href="https://t.me/your_channel">Название вашего канала</a>'
        )

    telegram_success = False
    media_paths = entry.get("media_paths", [])

    logger.info(
        f"Публикую прямую новость {message_id}, медиафайлов: {len(media_paths)}"
    )
    if media_paths:
        logger.info(f"Пути к медиафайлам: {media_paths}")
        for path in media_paths:
            if os.path.exists(path):
                size = os.path.getsize(path)
                logger.info(f"Файл существует: {path} (размер: {size} байт)")
            else:
                logger.error(f"Файл не существует: {path}")

    try:
        if media_paths:
            existing_media_paths = [
                path for path in media_paths if os.path.exists(path)
            ]
            logger.info(
                f"Существующих медиафайлов: {len(existing_media_paths)}/{len(media_paths)}"
            )

            if len(existing_media_paths) > 1:
                logger.info(
                    f"Отправляю альбом из {len(existing_media_paths)} файлов в Telegram"
                )
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    existing_media_paths,
                    caption=telegram_text,
                    parse_mode="HTML",
                )
            elif len(existing_media_paths) == 1:
                logger.info(
                    f"Отправляю одиночное медиа в Telegram: {existing_media_paths[0]}"
                )
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    existing_media_paths[0],
                    caption=telegram_text,
                    parse_mode="HTML",
                )
            else:
                logger.warning("Все медиафайлы недоступны, отправляю только текст")
                await clients.bot_client.send_message(
                    config.TARGET_ID, telegram_text, parse_mode="HTML"
                )
        else:
            logger.info(f"Отправляю только текст в Telegram (нет медиафайлов)")
            await clients.bot_client.send_message(
                config.TARGET_ID, telegram_text, parse_mode="HTML"
            )

        telegram_success = True
        logger.info(f"Published direct news {message_id} to Telegram")

    except Exception as e:
        logger.error(f"Error publishing direct news {message_id}: {e}", exc_info=True)
    finally:
        cleanup_media_files_direct(message_id)
        direct_news.pop(message_id, None)


async def reject_direct_news(message_id: int):
    """
    Rejects the publication of direct news from an admin.
    """
    cleanup_media_files_direct(message_id)
    direct_news.pop(message_id, None)
    logger.info(f"Rejected direct news {message_id}")


def cleanup_media_files_direct(message_id):
    """
    Cleans up downloaded media files for direct news.
    """
    message_dir = os.path.join(TEMP_MEDIA_DIR, f"direct_{message_id}")
    if os.path.exists(message_dir):
        try:
            shutil.rmtree(message_dir)
            logger.info(f"Cleaned up media files for direct news {message_id}")
        except Exception as e:
            logger.warning(
                f"Error cleaning up media files for direct news {message_id}: {e}"
            )


async def register_handlers():
    """
    Registers the message handler for direct news.
    """

    @clients.bot_client.on(events.NewMessage(chats=config.MODERATION_CHAT_ID))
    async def new_message_handler(event):
        await process_direct_message(event.message)
