# utils.py
import functools
import asyncio
from telethon.errors import RPCError, FloodWaitError
from logger import logger

def retry(tries: int = 3, delay: int = 2):
    """
    Декоратор с повтором запроса при сетевых/Telegram-ошибках.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(1, tries + 1):
                try:
                    return await func(*args, **kwargs)
                except (RPCError, FloodWaitError) as e:
                    logger.warning(f"Attempt {i} {func.__name__} failed: {e}")
                    if i == tries:
                        raise
                    await asyncio.sleep(delay * i)
        return wrapper
    return decorator