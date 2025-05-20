import asyncio
import asyncpg
import config
from logger import logger

# Connection pool for PostgreSQL
pool: asyncpg.Pool = None

async def init_db():
    """
    Initialize the database connection pool and ensure the processed_messages table exists.
    Update schema if needed to support multiple sources.
    """
    global pool
    pool = await asyncpg.create_pool(dsn=config.DATABASE_URL)
    async with pool.acquire() as conn:
        # Создаем таблицу, если она не существует
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            channel_id BIGINT,
            message_id BIGINT,
            source_type VARCHAR(10) DEFAULT 'telegram',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (channel_id, message_id, source_type)
        )
        """)
        
        # Проверяем, есть ли колонка source_type, и добавляем ее, если нет
        # (обратная совместимость с существующими базами данных)
        columns = await conn.fetch("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'processed_messages' AND column_name = 'source_type'
        """)
        
        if not columns:
            logger.info("Обновление схемы базы данных: добавление колонки source_type")
            await conn.execute("""
            ALTER TABLE processed_messages 
            ADD COLUMN source_type VARCHAR(10) DEFAULT 'telegram'
            """)
            
            # Обновляем первичный ключ
            await conn.execute("""
            ALTER TABLE processed_messages 
            DROP CONSTRAINT IF EXISTS processed_messages_pkey
            """)
            
            await conn.execute("""
            ALTER TABLE processed_messages 
            ADD PRIMARY KEY (channel_id, message_id, source_type)
            """)
            
    logger.info("Database initialized and processed_messages table ready.")

async def close_db():
    """
    Закрывает соединение с базой данных
    """
    global pool
    if pool:
        await pool.close()
        logger.info("Database connection pool closed")

async def check_processed(channel_id: int, message_id: int, source_type: str = "telegram") -> bool:
    """
    Check if a message (channel_id, message_id) has already been processed.
    
    Args:
        channel_id: ID канала/паблика
        message_id: ID сообщения/поста
        source_type: тип источника ('telegram' или 'vk')
    """
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            "SELECT 1 FROM processed_messages WHERE channel_id=$1 AND message_id=$2 AND source_type=$3",
            channel_id, message_id, source_type
        )
        return rec is not None

async def mark_processed(channel_id: int, message_id: int, source_type: str = "telegram"):
    """
    Mark a message as processed to prevent duplicate handling.
    
    Args:
        channel_id: ID канала/паблика
        message_id: ID сообщения/поста
        source_type: тип источника ('telegram' или 'vk')
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO processed_messages(channel_id, message_id, source_type) VALUES($1, $2, $3) ON CONFLICT DO NOTHING",
            channel_id, message_id, source_type
        )