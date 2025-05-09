import asyncio
from telethon import events
import config
import db
import requesty
import google_ai
import moderation
import clients
from logger import logger
import content_filter

async def _process_message(client, message):
    """
    Handle incoming message: deduplicate, reformulate text, and send to moderation.
    """
    # Determine channel and message IDs
    channel_id = getattr(message, 'chat_id', None) or getattr(message.peer_id, 'channel_id', None)
    message_id = message.id

    # Skip already processed messages
    if await db.check_processed(channel_id, message_id):
        return
    # Mark as processed to avoid duplications
    await db.mark_processed(channel_id, message_id)

    text = message.message or message.raw_text or ''
    if not text.strip():
        logger.info(f"Skipping empty message {channel_id}:{message_id}")
        return

    # Проверяем содержимое на рекламу и объявления о ракетной опасности
    try:
        is_filtered = await content_filter.check_content(text)
        if is_filtered:
            logger.info(f"Content filtered (ad or alert) {channel_id}:{message_id}")
            return
    except Exception as e:
        logger.error(f"Content filter check failed for {channel_id}:{message_id}: {e}")
        # Если проверка не удалась, продолжаем обработку (не фильтруем)

    # Reformulate text via Google AI API
    try:
        reformulated = await google_ai.reformulate_text(text)
    except Exception as e:
        logger.error(f"Reformulation failed for {channel_id}:{message_id}: {e}")
        return

    # Queue message for admin moderation
    await moderation.send_for_moderation(channel_id, message_id, reformulated, client, message)

async def _fetch_initial_history():
    """
    Process the last message from each source channel on startup.
    """
    # Use single tg_client to fetch last message from each source
    client = clients.tg_client
    for source_id in config.SOURCE_IDS:
        try:
            msgs = await client.get_messages(source_id, limit=1)
            if msgs:
                await _process_message(client, msgs[0])
        except Exception as e:
            logger.error(f"Initial fetch failed for {source_id}: {e}")

async def start_parser():
    """
    Initialize parser: fetch history and register new message handlers.
    """
    # Process backlog
    await _fetch_initial_history()

    # Register event handler on single user client
    def _make_handler(cli):
        async def handler(event):
            try:
                await _process_message(cli, event.message)
            except Exception as ex:
                logger.error(f"Error processing message: {ex}")
        return handler

    clients.tg_client.add_event_handler(
        _make_handler(clients.tg_client),
        events.NewMessage(chats=config.SOURCE_IDS)
    )
    logger.info("Parser is listening to new messages.") 