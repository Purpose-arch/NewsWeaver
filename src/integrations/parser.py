import asyncio
from telethon import events
import src.core.config as config
import src.integrations.requesty as requesty
import src.integrations.llm as llm
import src.features.moderation as moderation
import src.core.clients as clients
from src.core.logger import logger
import src.features.content_filter as content_filter


async def _process_message(client, message):
    """
    Handle incoming message: reformulate text, and send to moderation.
    """
    # Determine channel and message IDs
    channel_id = getattr(message, "chat_id", None) or getattr(
        message.peer_id, "channel_id", None
    )
    message_id = message.id

    text = message.message or message.raw_text or ""
    if not text.strip():
        logger.info(f"Skipping empty message {channel_id}:{message_id}")
        return

    try:
        is_filtered = await content_filter.check_content(text)
        if is_filtered:
            logger.info(f"Content filtered (ad or alert) {channel_id}:{message_id}")
            return
    except Exception as e:
        logger.error(f"Content filter check failed for {channel_id}:{message_id}: {e}")

    # Reformulate text via Langdock API
    try:
        reformulated = await llm.reformulate_text(text)
    except Exception as e:
        logger.error(f"Reformulation failed for {channel_id}:{message_id}: {e}")
        return

    # Queue message for admin moderation
    await moderation.send_for_moderation(
        channel_id, message_id, reformulated, client, message
    )


async def _fetch_initial_history():
    """
    Process the last message from each source channel on startup.
    """
    # Use single tg_client to fetch last message from each source
    client = clients.tg_client
    tasks = []
    for source_id in config.SOURCE_IDS:

        async def _fetch_and_process(src_id):
            try:
                msgs = await client.get_messages(src_id, limit=1)
                if msgs:
                    await _process_message(client, msgs[0])
            except Exception as e:
                logger.error(f"Initial fetch failed for {src_id}: {e}")

        tasks.append(_fetch_and_process(source_id))
    await asyncio.gather(*tasks)


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

    # Define a handler for both new and edited messages
    async def unified_handler(event):
        try:
            await _process_message(clients.tg_client, event.message)
        except Exception as ex:
            logger.error(f"Error processing message: {ex}")

    # Register handlers for both NewMessage and MessageEdited events
    clients.tg_client.add_event_handler(
        unified_handler, events.NewMessage(chats=config.SOURCE_IDS)
    )
    clients.tg_client.add_event_handler(
        unified_handler, events.MessageEdited(chats=config.SOURCE_IDS)
    )
    logger.info("Parser is listening to new and edited messages.")
