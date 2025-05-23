# media.py
import tempfile
from telethon import TelegramClient
from logger import logger
import clients
import fast_file_transfer

async def send_media(client: TelegramClient, target: int, message) -> list[str]:
    """
    Отправляем любые вложения (фото, видео, документы, стикеры и т.д.) из оригинального сообщения
    в целевой чат. Если прямая отправка не прошла, качаем локально и заливаем.
    Возвращает список локальных путей (если были скачаны).
    """
    saved = []
    if not message.media:
        return saved

    # Use bot client for sending media
    send_client = clients.bot_client
    try:
        # Try to directly resend via bot
        await send_client.send_file(target, message.media)
    except Exception as e:
        logger.warning(f"Direct send_file failed: {e}, fallback to download+send")
        with tempfile.TemporaryDirectory() as tmp:
            # Download media using original client
            path = await client.download_media(message, file=tmp)
            # Send downloaded file via bot
            await send_client.send_file(target, path)
            saved.append(path)

    return saved