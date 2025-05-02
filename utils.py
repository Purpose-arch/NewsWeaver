# utils.py
import functools
import asyncio
from telethon.errors import RPCError, FloodWaitError
from logger import logger
import re

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

def markdown_to_html(text):
    """
    Преобразует Markdown-разметку в HTML-теги.
    Поддерживает основные элементы: **жирный**, *курсив*, __подчеркнутый__, ~~зачеркнутый~~, `код`.
    """
    if not text:
        return text
        
    # Жирный текст: **текст** -> <b>текст</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    
    # Курсив: *текст* -> <i>текст</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    
    # Подчеркнутый: __текст__ -> <u>текст</u>
    text = re.sub(r'__(.*?)__', r'<u>\1</u>', text)
    
    # Зачеркнутый: ~~текст~~ -> <s>текст</s>
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    
    # Моноширинный: `текст` -> <code>текст</code>
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    
    # Ссылки: [текст](url) -> <a href="url">текст</a>
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
    
    return text