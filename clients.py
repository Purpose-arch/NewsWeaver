import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
import config
from logger import logger

# Initialize single user session client
user_client = TelegramClient(
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
    Start all Telethon clients: user sessions and bot session.
    """
    # Start single user client
    await user_client.start()
    logger.info(f"User client started: {user_client.session}")
    # Start bot client with token
    await bot_client.start(bot_token=config.BOT_TOKEN)
    logger.info("Bot client started with BOT_TOKEN")

# Expose loop for scheduling tasks if needed
loop = asyncio.get_event_loop() 