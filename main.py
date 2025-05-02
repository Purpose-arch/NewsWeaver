# main.py
import asyncio
from logger import logger
import db
import clients
import parser
import moderation
import requesty
import publisher
import direct_news

async def main():
    logger.info("→ Initialize database")
    await db.init_db()

    logger.info("→ Start Telegram clients")
    await clients.start_clients()

    logger.info("→ Register moderation handlers")
    await moderation.register_handlers()

    logger.info("→ Start parser")
    await parser.start_parser()

    logger.info("→ Schedule cleanup_old task")
    asyncio.create_task(db.schedule_cleanup(1))

    logger.info("✅ Bot is up and running")
    # Await disconnection of bot and single user client
    await asyncio.gather(
        clients.bot_client.disconnected,
        clients.user_client.disconnected
    )

if __name__ == "__main__":
    asyncio.run(main())