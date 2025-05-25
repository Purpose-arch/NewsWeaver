# pre_moderation.py
import re
from logger import logger

def clean_blockquote_prefix(text: str) -> str:
    """
    Removes any non-whitespace character immediately preceding a blockquote tag.
    This is to clean up cases where an emoji or other character is stuck
    right before the blockquote, which can break formatting.

    Args:
        text: The input news text, potentially containing blockquote tags.

    Returns:
        The cleaned text with unwanted prefixes before blockquotes removed.
    """
    # Regex to find any non-whitespace character (\S) immediately followed by <blockquote>
    # We capture the blockquote tag in group 2 so we can keep it.
    pattern = r"(\S)(<blockquote>)"

    # Replace found patterns with just the blockquote tag (group 2)
    cleaned_text = re.sub(pattern, r"\2", text)

    if cleaned_text != text:
        logger.info("Cleaned up blockquote prefixes in text.")

    return cleaned_text
