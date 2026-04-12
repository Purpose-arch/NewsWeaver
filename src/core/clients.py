import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import FloodWaitError
import src.core.config as config
from src.core.logger import logger
import src.features.publisher as publisher

# Initialize single user session client
tg_client = TelegramClient(
    StringSession(config.STRING_SESSION), config.API_ID, config.API_HASH
)

# Initialize bot client for moderation and publishing
# Uses an ephemeral session; authorization via BOT_TOKEN
bot_client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)


async def start_clients():
    """
    Starts all clients for the service.
    """
    global tg_client, bot_client

    await tg_client.start()
    logger.info(f"User client started: {tg_client.session}")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            await bot_client.start(bot_token=config.BOT_TOKEN)
            logger.info("Bot client started with BOT_TOKEN")
            break
        except FloodWaitError as e:
            logger.warning(
                f"FloodWaitError: Требуется подождать {e.seconds} секунд. Повторная попытка через {e.seconds} секунд... (Попытка {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(e.seconds)
            if attempt == max_retries - 1:
                logger.error(
                    f"Не удалось запустить бот-клиент после {max_retries} попыток из-за FloodWaitError."
                )
                raise
        except Exception as e:
            logger.error(
                f"Произошла непредвиденная ошибка при запуске бот-клиента: {e}",
                exc_info=True,
            )
            raise

    return tg_client, bot_client


async def close_clients():
    """
    Gracefully closes all client connections.
    """
    global tg_client, bot_client

    if tg_client:
        await tg_client.disconnect()
        logger.info("TG клиент отключен")

    if bot_client:
        await bot_client.disconnect()
        logger.info("Bot клиент отключен")


# Expose loop for scheduling tasks if needed
loop = asyncio.get_event_loop()
