# logger.py
import sys
import logging

logger = logging.getLogger("telegram_bot")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
