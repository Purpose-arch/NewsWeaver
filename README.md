<div align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/aiogram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Aiogram">
  <img src="https://img.shields.io/badge/Telethon-00aced?style=for-the-badge&logo=telegram&logoColor=white" alt="Telethon">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</div>

<p align="center">
  <a href="#english-en">English</a> •
  <a href="#русский-ru">Русский</a>
</p>

# NewsWeaver Telegram Bot

---

<h2 id="english-en">🇬🇧 English (EN)</h2>

News aggregator for Telegram channels with automatic text rewriting via LLM.

### How it works

The bot forwards, rewrites, and publishes posts from donor channels:
1. Parses new posts from the list of specified sources.
2. Filters ads, spam, or junk content by keywords.
3. Sends the post text to an LLM model (via OpenAI API or any other compatible API) for rewriting.
4. The generated draft is sent to a private chat for moderation.
5. A moderator reviews the text. By clicking the "Approve" button, the post is published to the target channel. By clicking "Reject", it is deleted.
6. In the moderation chat, you can reply to the draft with your feedback, and the bot will rewrite the news taking your edits into account.
7. The bot handles attachments flawlessly (photos, videos, and media albums up to 10 files).

### Running (Docker)

1. Create a configuration from the example:
```bash
cp .env.example .env
```

2. Fill in the required parameters in `.env`:
- `API_ID` and `API_HASH` — get your keys at [my.telegram.org](https://my.telegram.org)
- `BOT_TOKEN` — your bot's token
- `LLM_API_KEY` — OpenAI API key (or another provider like Groq or DeepSeek)
- `LLM_BASE_URL` — API base address (if you use something other than OpenAI)
- `LLM_MODEL_NAME` — model name (e.g., `gpt-4o-mini`)
- `SOURCE_IDS` — donor channel IDs (comma separated)
- `TARGET_ID` — ID of your main channel where the posts will be published
- `MODERATION_CHAT_ID` — ID of the moderation chat or group

3. Build and run the bot:
```bash
docker-compose up -d --build
```

**Please note:** The Telethon client session (userbot) is used to parse posts from other's channels. On the very first run, you will need to authorize this account and enter the code from Telegram. If you don't have a ready session string (`STRING_SESSION`) yet, run the project locally once: install dependencies (`pip install -r requirements.txt`) and run `python src/core/main.py`. After authorization, the bot will give you a session string - paste it into `.env` and then run via Docker.

---

<h2 id="русский-ru">🇷🇺 Русский (RU)</h2>

Агрегатор новостей для Telegram-каналов с функцией автоматического переписывания текста (рерайта) через LLM.

### Как это работает

Бот пересылает, переписывает и публикует посты из каналов-доноров:
1. Парсит новые записи из списка указанных источников.
2. Фильтрует рекламу, спам или мусорный контент по ключевым словам.
3. Отправляет текст поста в LLM-модель (через API OpenAI или любое другое совместимое API) для переписывания.
4. Готовый черновик отправляется в закрытый чат для модерации.
5. Модератор проверяет текст. По нажатию кнопки "Одобрить" пост публикуется в целевой канал, по кнопке "Отклонить" — удаляется.
6. В чате модерации можно ответить (reply) на черновик текстом замечания, и бот перепишет новость с учетом ваших правок.
7. Бот корректно работает со вложениями (фото, видео и медиа-альбомы до 10 файлов).

### Запуск (Docker)

1. Создайте конфигурацию из примера:
```bash
cp .env.example .env
```

2. Впишите нужные параметры в `.env`:
- `API_ID` и `API_HASH` — получите ключи на [my.telegram.org](https://my.telegram.org)
- `BOT_TOKEN` — токен вашего бота
- `LLM_API_KEY` — ключ от OpenAI (или другого провайдера, например Groq или DeepSeek)
- `LLM_BASE_URL` — базовый адрес API (если используете не OpenAI)
- `LLM_MODEL_NAME` — название модели (например, `gpt-4o-mini`)
- `SOURCE_IDS` — ID каналов-доноров (пишутся через запятую)
- `TARGET_ID` — ID вашего основного канала, куда будут выходить посты
- `MODERATION_CHAT_ID` — ID чата или группы для модерации

3. Соберите и запустите бота:
```bash
docker-compose up -d --build
```

**Обратите внимание:** для парсинга постов из чужих каналов используется клиентская сессия (юзербот) Telethon. При самом первом запуске потребуется авторизовать этот аккаунт и ввести код из Telegram. Если у вас еще нет готовой строки сессии (`STRING_SESSION`), запустите проект один раз локально: установите зависимости (`pip install -r requirements.txt`) и запустите `python src/core/main.py`. После авторизации бот выдаст вам строку сессии — вставьте её в `.env` и дальше запускайте через Docker без проблем.