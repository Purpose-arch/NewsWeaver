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
# Источники для парсинга
SOURCE_IDS     = parse_list("SOURCE_IDS", int)
# Админы для модерации
ADMIN_IDS      = parse_list("ADMIN_IDS", int)

# Bot API и куда публиковать
BOT_TOKEN      = os.getenv("BOT_TOKEN")
TARGET_ID      = int(os.getenv("TARGET_ID", "0"))

# PostgreSQL (fallback defaults to avoid None)
DB_HOST        = os.getenv("DB_HOST", "localhost")
DB_PORT        = os.getenv("DB_PORT", "5432")
DB_NAME        = os.getenv("DB_NAME", "postgres")
DB_USER        = os.getenv("DB_USER", "postgres")
DB_PASSWORD    = os.getenv("DB_PASSWORD", "")
# Use full DATABASE_URL if provided (e.g. Railway plugin), otherwise build DSN
DATABASE_URL   = os.getenv("DATABASE_URL") or (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ID группового чата для модерации новостей
# Этот чат используется для отправки новостей на модерацию
# Бот должен быть администратором в этом чате
MODERATION_CHAT_ID = int(os.getenv("MODERATION_CHAT_ID", "0"))