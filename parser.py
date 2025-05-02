import asyncio
from telethon import events
import config
import db
import requesty
import moderation
import clients
from logger import logger

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

    # Reformulate text via Requesty
    try:
        reformulated = await requesty.reformulate_text(text)
    except Exception as e:
        logger.error(f"Reformulation failed for {channel_id}:{message_id}: {e}")
        return

    # Queue message for admin moderation
    await moderation.send_for_moderation(channel_id, message_id, reformulated, client, message)

async def _fetch_initial_history():
    """
    Process the last message from each source channel on startup.
    """
    # Use single user_client to fetch last message from each source
    client = clients.user_client
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

    clients.user_client.add_event_handler(
        _make_handler(clients.user_client),
        events.NewMessage(chats=config.SOURCE_IDS)
    )
    logger.info("Parser is listening to new messages.") 