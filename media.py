# media.py
import tempfile
from telethon import TelegramClient
from logger import logger

async def send_media(client: TelegramClient, target: int, message) -> list[str]:
    """
    Отправляем любые вложения (фото, видео, документы, стикеры и т.д.) из оригинального сообщения
    в целевой чат. Если прямая отправка не прошла, качаем локально и заливаем.
    Возвращает список локальных путей (если были скачаны).
    """
    saved = []
    if not message.media:
        return saved

    try:
        # Пробуем сразу переотправить
        await client.send_file(target, message.media)
    except Exception as e:
        logger.warning(f"Direct send_file failed: {e}, fallback to download+send")
        with tempfile.TemporaryDirectory() as tmp:
            path = await client.download_media(message, file=tmp)
            await client.send_file(target, path)
            saved.append(path)

    return saved