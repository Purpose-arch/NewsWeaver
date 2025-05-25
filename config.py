import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

def parse_list(var_name: str, cast_type=str):
    val = os.getenv(var_name, "")
    if not val:
        return []
    return [cast_type(i.strip()) for i in val.split(",") if i.strip()]

# Telegram API (single session)
API_ID         = int(os.getenv("API_ID"))
API_HASH       = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

# API keys
REQUESTY_APIS  = parse_list("REQUESTY_APIS", str)
GOOGLE_AI_API_KEYS = parse_list("GOOGLE_AI_API_KEYS", str)
# Список моделей в порядке приоритета (если одна не работает, используем следующую)
AI_MODELS = parse_list("AI_MODELS", str) or ["gemini-2.5-pro-exp-03-25", "gemini-1.5-pro", "gemini-1.5-flash"]

# VoidAI API
VOIDAI_API_KEYS = parse_list("VOIDAI_API_KEYS", str)
# Список моделей VoidAI в порядке приоритета
VOIDAI_MODELS = parse_list("VOIDAI_MODELS", str) or ["claude-3-5-sonnet-20241022", "gpt-4o", "gemini-1.5-pro"]

# Источники для парсинга
SOURCE_IDS     = parse_list("SOURCE_IDS", int)
# Админы для модерации
ADMIN_IDS      = parse_list("ADMIN_IDS", int)

# Bot API и куда публиковать
BOT_TOKEN      = os.getenv("BOT_TOKEN")
TARGET_ID      = int(os.getenv("TARGET_ID", "0"))

# Конфигурация для alert bot (rocket/UAV alerts)
# Канал или чат для мониторинга оповещений о воздушных тревогах
SOURCE_CHANNEL_ID = os.getenv("SOURCE_CHANNEL_ID", "")
# Публикация осуществляется в тот же канал, что и основной бот (TARGET_ID)

# ID группового чата для модерации новостей
# Этот чат используется для отправки новостей на модерацию
# Бот должен быть администратором в этом чате
MODERATION_CHAT_ID = int(os.getenv("MODERATION_CHAT_ID", "0"))