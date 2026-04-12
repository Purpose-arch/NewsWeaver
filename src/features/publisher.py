# publisher.py
import src.core.config as config
import tempfile
from src.core.logger import logger
import src.utils.media as media
import src.core.clients as clients
import src.features.moderation as moderation
import os
from src.utils.utils import markdown_to_html
import asyncio
import aiohttp
import io
import requests


async def publish(channel_id: int, message_id: int, source_type: str = "telegram"):
    """
    On "Accept", sends the photo (if any) with the caption (reformulated text)
    to TARGET_ID, then clears pending.

    Args:
        channel_id: Source channel/public page ID
        message_id: Message/post ID
        source_type: Source type ("telegram" or "vk")
    """
    key = (channel_id, message_id)
    entry = moderation.pending.get(key)
    if not entry:
        logger.error(f"No pending entry to publish {key}")
        return

    text = markdown_to_html(entry["text"])

    telegram_text = (
        f'{text}\n\n📰 <a href="https://t.me/your_channel">Название вашего канала</a>'
    )

    media_paths = entry.get("media_paths", [])

    logger.info(
        f"Публикую новость {key} (source: {source_type}), медиафайлов: {len(media_paths)}"
    )
    if media_paths:
        logger.info(f"Пути к медиафайлам: {media_paths}")
        for path in media_paths:
            if os.path.exists(path):
                size = os.path.getsize(path)
                logger.info(f"Файл существует: {path} (размер: {size} байт)")
            else:
                logger.error(f"Файл не существует: {path}")

    telegram_success = False

    try:
        if media_paths:
            existing_media_paths = [
                path for path in media_paths if os.path.exists(path)
            ]
            logger.info(
                f"Существующих медиафайлов: {len(existing_media_paths)}/{len(media_paths)}"
            )

            if existing_media_paths:
                logger.info(
                    f"Using pre-downloaded media files for {key} (source: {source_type})"
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
                else:
                    logger.info(
                        f"Отправляю одиночное медиа в Telegram: {existing_media_paths[0]}"
                    )
                    await clients.bot_client.send_file(
                        config.TARGET_ID,
                        existing_media_paths[0],
                        caption=telegram_text,
                        parse_mode="HTML",
                    )
                telegram_success = True
                media_paths = existing_media_paths
            else:
                logger.warning(
                    f"Все предварительно скачанные медиафайлы недоступны, пытаюсь скачать заново"
                )

            if not telegram_success:
                original = entry["message"]
                client = entry.get("client")

                if source_type == "telegram" and getattr(original, "media", None):
                    grouped_id = getattr(original, "grouped_id", None)
                    entity = getattr(original, "chat_id", None) or getattr(
                        original.peer_id, "channel_id", None
                    )
                    with tempfile.TemporaryDirectory() as tmp:
                        if grouped_id:
                            # fetch all messages from the same album
                            msgs = await client.get_messages(entity, limit=100)
                            media_msgs = [
                                m
                                for m in msgs
                                if getattr(m, "grouped_id", None) == grouped_id
                            ]
                            media_msgs.sort(key=lambda m: m.id)
                            paths = []
                            for msg in media_msgs:
                                if getattr(msg, "media", None):
                                    path = await client.download_media(msg, file=tmp)
                                    if path:
                                        paths.append(path)

                            if not paths:
                                raise ValueError(
                                    "Не удалось скачать медиафайлы из альбома"
                                )

                            await clients.bot_client.send_file(
                                config.TARGET_ID,
                                paths,
                                caption=telegram_text,
                                parse_mode="HTML",
                            )
                            telegram_success = True

                            media_paths = paths.copy()
                        else:
                            path = await client.download_media(original, file=tmp)
                            await clients.bot_client.send_file(
                                config.TARGET_ID,
                                path,
                                caption=telegram_text,
                                parse_mode="HTML",
                            )
                            telegram_success = True

                            media_paths = [path]
                else:
                    logger.info(f"Отправляю только текст в Telegram (нет медиафайлов)")
                    await clients.bot_client.send_message(
                        config.TARGET_ID, telegram_text, parse_mode="HTML"
                    )
                    telegram_success = True
        else:
            logger.info(f"Отправляю только текст в Telegram (нет медиафайлов совсем)")
            await clients.bot_client.send_message(
                config.TARGET_ID, telegram_text, parse_mode="HTML"
            )
            telegram_success = True

    except Exception as e:
        logger.error(
            f"Error publishing message {key} (source: {source_type}): {e}",
            exc_info=True,
        )
    finally:
        try:
            moderation.cleanup_media_files(key)
        except Exception as e:
            logger.warning(f"Error cleaning media files: {e}")

        moderation.pending.pop(key, None)
        logger.info(f"Published {key} (source: {source_type})")


async def reject(channel_id: int, message_id: int, source_type: str = "telegram"):
    """
    On "Reject", cleans up temporary files and removes from pending.

    Args:
        channel_id: Source channel/public page ID
        message_id: Message/post ID
        source_type: Source type ("telegram" or "vk")
    """
    key = (channel_id, message_id)

    try:
        moderation.cleanup_media_files(key)
    except Exception as e:
        logger.warning(f"Error cleaning media files: {e}")

    moderation.pending.pop(key, None)
    logger.info(f"Rejected {key} (source: {source_type})")
