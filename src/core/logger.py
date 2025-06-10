# logger.py
import sys
import logging

logger = logging.getLogger("telegram_bot")

# Проверяем, не настроен ли уже логгер, чтобы избежать дублирования логов
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)