# Новостной бот

Бот для сбора, обработки и публикации новостного контента из Telegram-каналов и групп ВКонтакте.

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

# ВКонтакте API для парсинга пабликов
VK_TOKEN=your_vk_token_here
# ID пабликов ВК для парсинга (через запятую)
VK_GROUP_IDS=12345,67890
# Интервал проверки новых постов в секундах (по умолчанию 300)
VK_POLL_INTERVAL=300
```

### Дополнительные параметры

```
# ID модераторов (через запятую)
ADMIN_IDS=123456789

# База данных PostgreSQL
DATABASE_URL=postgresql://postgres:password@localhost:5432/newsbot
```

## Получение VK_TOKEN

Для работы с API ВКонтакте необходимо получить токен доступа. Вы можете создать токен для вашего аккаунта следующим образом:

1. Создайте приложение на странице https://vk.com/apps?act=manage
2. В настройках приложения скопируйте ID приложения
3. Перейдите по ссылке:
   ```
   https://oauth.vk.com/authorize?client_id=YOUR_APP_ID&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=wall,offline&response_type=token&v=5.131
   ```
   Заменив `YOUR_APP_ID` на ID вашего приложения
4. Разрешите доступ приложению
5. В адресной строке будет URL с токеном: `https://oauth.vk.com/blank.html#access_token=YOUR_TOKEN&...`
6. Скопируйте значение токена и укажите его в `.env` файле как `VK_TOKEN`

## Запуск

```bash
pip install -r requirements.txt
python main.py
``` 