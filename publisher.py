# publisher.py
import config
from logger import logger
import media
import clients
import moderation

async def publish(channel_id: int, message_id: int):
    """
    При «Принять» отправляет текст и медиа в TARGET_ID, потом чистит pending.
    """
    key = (channel_id, message_id)
    entry = moderation.pending.get(key)
    if not entry:
        logger.error(f"No pending entry to publish {key}")
        return

    text = entry["text"]
    original = entry["message"]

    # Отправляем HTML-текст
    await clients.bot_client.send_message(
        config.TARGET_ID, text, parse_mode='HTML'
    )
    # Отправляем вложения
    await media.send_media(clients.bot_client, config.TARGET_ID, original)

    moderation.pending.pop(key, None)
    logger.info(f"Published {key}")

async def reject(channel_id: int, message_id: int):
    """
    При «Отклонить» просто удаляем из pending.
    """
    key = (channel_id, message_id)
    moderation.pending.pop(key, None)
    logger.info(f"Rejected {key}")