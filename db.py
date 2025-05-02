import asyncio
import asyncpg
import config
from logger import logger

# Connection pool for PostgreSQL
pool: asyncpg.Pool = None

async def init_db():
    """
    Initialize the database connection pool and ensure the processed_messages table exists.
    """
    global pool
    pool = await asyncpg.create_pool(dsn=config.DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            channel_id BIGINT,
            message_id BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (channel_id, message_id)
        )
        """)
    logger.info("Database initialized and processed_messages table ready.")

async def check_processed(channel_id: int, message_id: int) -> bool:
    """
    Check if a message (channel_id, message_id) has already been processed.
    """
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            "SELECT 1 FROM processed_messages WHERE channel_id=$1 AND message_id=$2",
            channel_id, message_id
        )
        return rec is not None

async def mark_processed(channel_id: int, message_id: int):
    """
    Mark a message as processed to prevent duplicate handling.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO processed_messages(channel_id, message_id) VALUES($1, $2) ON CONFLICT DO NOTHING",
            channel_id, message_id
        )

async def cleanup_old():
    """
    Delete processed message records older than 24 hours.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM processed_messages WHERE created_at < NOW() - INTERVAL '24 hours'"
        )
    logger.info(f"cleanup_old result: {result}")

async def schedule_cleanup(interval_hours: int = 1):
    """
    Periodically run cleanup_old every interval_hours.
    """
    while True:
        try:
            await cleanup_old()
        except Exception as e:
            logger.error(f"Error during cleanup_old: {e}")
        await asyncio.sleep(interval_hours * 3600) 