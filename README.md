# Новостной бот

Бот для сбора, обработки и публикации новостного контента из Telegram-каналов.

## Настройка переменных окружения

Для работы бота необходимо создать файл `.env` в корневой директории проекта и указать в нем следующие параметры:

### Обязательные параметры

```
# Telegram API
API_ID=123456
API_HASH=your_api_hash_here
STRING_SESSION=your_session_string_here

# Google AI API для реформулирования текстов
GOOGLE_AI_API_KEYS=key1,key2
AI_MODELS=gemini-2.5-pro-exp-03-25,gemini-1.5-pro,gemini-1.5-flash

# Бот для модерации и публикации
BOT_TOKEN=your_bot_token_here

# ID группового чата для модерации
MODERATION_CHAT_ID=-100123456789

# ID канала для публикации
TARGET_ID=-100987654321
```

### Источники новостей

```
# ID Telegram-каналов для парсинга новостей (через запятую)
SOURCE_IDS=-100123456789,-100987654321
```

### Дополнительные параметры

```
# ID модераторов (через запятую)
ADMIN_IDS=123456789

# База данных PostgreSQL
DATABASE_URL=postgresql://postgres:password@localhost:5432/newsbot
```

## Запуск

```bash
pip install -r requirements.txt
python main.py
``` 