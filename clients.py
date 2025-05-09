import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
import config
from logger import logger
import vk_clients
import publisher

# Initialize single user session client
tg_client = TelegramClient(
    StringSession(config.STRING_SESSION),
    config.API_ID,
    config.API_HASH
)

# Initialize bot client for moderation and publishing
# Uses an ephemeral session; authorization via BOT_TOKEN
bot_client = TelegramClient(
    StringSession(),
    config.API_ID,
    config.API_HASH
)

async def start_clients():
    """
    Запускает всех клиентов для сервиса
    """
    global tg_client, bot_client
    
    # Запускаем основной клиент пользователя
    await tg_client.start()
    logger.info(f"User client started: {tg_client.session}")
    
    # Запускаем бот-клиент для публикации
    await bot_client.start(bot_token=config.BOT_TOKEN)
    logger.info("Bot client started with BOT_TOKEN")
    
    # Запускаем VK клиент для парсинга
    await vk_clients.start_vk_client()
    
    # Запускаем VK клиент для публикации
    await publisher.init_vk_publish_client()
    
    return tg_client, bot_client

async def close_clients():
    """
    Корректно закрывает все подключения клиентов
    """
    global tg_client, bot_client
    
    # Закрываем VK клиент для публикации
    await publisher.close_vk_publish_client()
    
    # Закрываем VK клиент для парсинга
    await vk_clients.close_vk_client()
    
    # Закрываем Telegram клиенты
    if tg_client:
        await tg_client.disconnect()
        logger.info("TG клиент отключен")
    
    if bot_client:
        await bot_client.disconnect()
        logger.info("Bot клиент отключен")

# Expose loop for scheduling tasks if needed
loop = asyncio.get_event_loop() 