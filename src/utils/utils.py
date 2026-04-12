# utils.py
import functools
import asyncio
from telethon.errors import RPCError, FloodWaitError
from src.core.logger import logger
import re


def retry(tries: int = 3, delay: int = 2):
    """
    Decorator that retries the request on network/Telegram errors.
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


def markdown_to_html(text):
    """
    Converts Markdown to HTML tags.
    Supports basic elements: **bold**, *italic*, __underline__, ~~strikethrough~~, `code`.
    """
    if not text:
        return text

    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)

    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)

    text = re.sub(r"__(.*?)__", r"<u>\1</u>", text)

    text = re.sub(r"~~(.*?)~~", r"<s>\1</s>", text)

    text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)

    text = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', text)

    return text
