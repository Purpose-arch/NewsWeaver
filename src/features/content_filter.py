# content_filter.py
import asyncio
import src.core.config as config
from src.core.logger import logger
import src.integrations.llm as llm


async def check_content(text: str) -> bool:
    """
    Checks the news content via LLM API.

    Args:
        text: News text to check

    Returns:
        bool: True if the message should be filtered (ad or danger announcement),
              False if the message is suitable for reformulation
    """
    try:
        return await llm.check_content(text)
    except Exception as e:
        logger.critical(
            f"Critical error during content check with LLM API: {e}. Defaulting to not filtered."
        )
        return False
