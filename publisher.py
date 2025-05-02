# publisher.py
import config
import tempfile
from logger import logger
import media
import clients
import moderation

async def publish(channel_id: int, message_id: int):
    """
    При «Принять» отправляет фото (если есть) с подписью (переформулированным текстом)
    в TARGET_ID, потом чистит pending.
    """
    key = (channel_id, message_id)
    entry = moderation.pending.get(key)
    if not entry:
        logger.error(f"No pending entry to publish {key}")
        return

    text = entry["text"]
    # append footer link
    text = f"{text}\n\n📰 <a href=\"https://t.me/fatezhinteresting\">Фатежский Вестник</a>"
    original = entry["message"]
    client = entry.get("client")  # исходный клиент для загрузки media

    # если есть вложение, скачиваем его и отправляем с caption
    if getattr(original, "media", None):
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
            else:
                path = await client.download_media(original, file=tmp)
                await clients.bot_client.send_file(
                    config.TARGET_ID,
                    path,
                    caption=text,
                    parse_mode='HTML'
                )
    else:
        # иначе просто отправляем текст
        await clients.bot_client.send_message(
            config.TARGET_ID,
            text,
            parse_mode='HTML'
        )

    # очищаем pending и логируем
    moderation.pending.pop(key, None)
    logger.info(f"Published {key}")

async def reject(channel_id: int, message_id: int):
    """
    При «Отклонить» просто удаляем из pending.
    """
    key = (channel_id, message_id)
    moderation.pending.pop(key, None)
    logger.info(f"Rejected {key}")