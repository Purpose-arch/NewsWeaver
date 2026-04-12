import asyncio
import os
import logging
import time
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Message
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
import src.core.config as config

logger = logging.getLogger(__name__)
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

alarm_client = TelegramClient(
    StringSession(config.STRING_SESSION), config.API_ID, config.API_HASH
)
bot = Bot(token=config.BOT_TOKEN)


async def get_entity_id(client, entity_str):
    try:
        return int(entity_str)
    except ValueError:
        try:
            entity = await client.get_entity(entity_str)
            return entity.id
        except ValueError as e:
            logger.warning(
                f"Could not find entity '{entity_str}' using get_entity: {e}. Trying as input peer..."
            )
            logger.warning(
                f"Resolving '{entity_str}' as InputPeer is complex. Relying on get_entity or direct ID."
            )
            return None
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while getting entity '{entity_str}': {e}"
            )
            return None


alert_message = f"🔴 <b>РАКЕТНАЯ ОПАСНОСТЬ!</b>"

off_message = f"🟢 <b>ОТБОЙ РАКЕТНОЙ ОПАСНОСТИ!</b>"

uav_alert_message = f"🔴 <b>УГРОЗА БПЛА!</b>"

uav_off_message = f"🟢 <b>ОТБОЙ УГРОЗЫ БПЛА!</b>"


last_alert_message_id: int | None = None
last_uav_alert_message_id: int | None = None
processed_events = {}
DUPLICATE_EVENT_WINDOW_SECONDS = 5


def should_process_event(event: events.common.EventCommon) -> bool:
    """Checks if the event should be processed, using deduplication."""
    global processed_events
    current_time = time.time()

    event_key = hash(event)
    if hasattr(event, "message") and hasattr(event.message, "id"):
        event_key = (
            event.message.id
        )

    if event_key in processed_events and (
        current_time - processed_events[event_key] < DUPLICATE_EVENT_WINDOW_SECONDS
    ):
        logger.warning(
            f"Skipping duplicate event processing for key {event_key} within {DUPLICATE_EVENT_WINDOW_SECONDS} seconds. Event type: {type(event).__name__}"
        )
        return False

    processed_events[event_key] = current_time

    cleanup_threshold = current_time - (DUPLICATE_EVENT_WINDOW_SECONDS * 10)
    keys_to_delete = [
        key for key, ts in processed_events.items() if ts < cleanup_threshold
    ]
    for key in keys_to_delete:
        if (
            key in processed_events
        ):
            del processed_events[key]

    return True


async def send_bot_message(target_chat_id, text_to_send, original_message_id):
    """Sends a message via the Aiogram bot with error handling."""
    try:
        await bot.send_message(
            chat_id=target_chat_id,
            text=text_to_send,
            parse_mode="HTML",
            disable_web_page_preview=True,
            disable_notification=False,
        )
        logger.info(
            f"Message based on original ID {original_message_id} sent successfully to {target_chat_id}"
        )
    except TelegramBadRequest as e:
        logger.error(
            f"Failed to send message based on original ID {original_message_id} to {target_chat_id}: {e}"
        )
    except Exception as e:
        logger.error(
            f"Unexpected error sending message based on original ID {original_message_id}: {e}",
            exc_info=True,
        )


async def handle_new_message(event: events.NewMessage.Event):
    """Handles only new messages."""
    global last_alert_message_id, last_uav_alert_message_id
    message: Message = event.message

    if not should_process_event(event):
        return

    if not hasattr(message, "text") or not message.text:
        logger.debug(f"New message {message.id} has no text, skipping.")
        return

    logger.info(f"Processing new message: ID={message.id} from chat={message.chat_id}")
    text_lower = message.text.lower()
    target_chat = config.TARGET_ID
    has_target_location = (
        "ваша область" in text_lower or "ваш район" in text_lower
    )

    if has_target_location and "опасность атаки бпла" in text_lower:
        logger.info(
            f"New message {message.id} contains UAV alert phrase for target location. Sending UAV alert and storing ID."
        )
        await send_bot_message(target_chat, uav_alert_message, message.id)
        last_uav_alert_message_id = message.id
    elif has_target_location and "отбой" in text_lower and "бпла" in text_lower:
        logger.info(
            f"New message {message.id} contains 'UAV off' phrase for target location. Sending UAV off message and clearing UAV alert ID."
        )
        await send_bot_message(target_chat, uav_off_message, message.id)
        last_uav_alert_message_id = None
    elif has_target_location and "ракетная опасность" in text_lower:
        if "отбой" not in text_lower:
            logger.info(
                f"New message {message.id} contains missile alert phrase ('ракетная опасность') for target location. Sending missile alert and storing ID."
            )
            await send_bot_message(target_chat, alert_message, message.id)
            last_alert_message_id = (
                message.id
            )
        else:
            logger.info(
                f"New message {message.id} contains 'ракетная опасность' but also 'отбой' for target location. Assuming it is an 'off' message handled separately."
            )
    elif has_target_location and "отбой" in text_lower and "ракетн" in text_lower:
        logger.info(
            f"New message {message.id} contains 'missile off' phrase for target location. Sending missile off message and clearing alert ID."
        )
        await send_bot_message(target_chat, off_message, message.id)
        last_alert_message_id = None
    else:
        logger.info(
            f"New message {message.id} does not contain target phrases. Skipping."
        )


async def start_alarm_bot():
    """Starts the alarm bot for missile and UAV threat alerts."""
    global last_alert_message_id, last_uav_alert_message_id

    if not config.SOURCE_CHANNEL_ID:
        logger.error(
            "Missing SOURCE_CHANNEL_ID for alarm bot. Skipping alarm bot startup."
        )
        return False

    if config.TARGET_ID == 0:
        logger.error(
            "TARGET_ID is not set or invalid. Alarm bot needs a valid target channel ID."
        )
        return False

    try:
        source_entity_id = await get_entity_id(alarm_client, config.SOURCE_CHANNEL_ID)
        if source_entity_id is None:
            logger.error(
                f"Could not resolve source channel: {config.SOURCE_CHANNEL_ID}. Alarm bot not started."
            )
            return False

        logger.info(f"Successfully resolved source entity: {source_entity_id}")
        logger.info(
            f"Using target channel ID: {config.TARGET_ID} for publishing alerts"
        )

        if not alarm_client.is_connected():
            await alarm_client.start()
            logger.info("Alarm bot Telethon client started")

        await bot.delete_webhook(drop_pending_updates=True)

        alarm_client.add_event_handler(
            handle_new_message, events.NewMessage(chats=source_entity_id)
        )

        logger.info("Alarm bot started: monitoring alerts")
        logger.info(
            f"Listening for events in source channel: {config.SOURCE_CHANNEL_ID} (resolved ID: {source_entity_id})"
        )
        logger.info(f"Sending custom alert/off messages to target: {config.TARGET_ID}")

        return True
    except Exception as e:
        logger.error(f"Error starting alarm bot: {e}", exc_info=True)
        return False


async def stop_alarm_bot():
    """Stops the alarm bot."""
    try:
        if alarm_client.is_connected():
            await alarm_client.disconnect()
            logger.info("Alarm bot Telethon client disconnected")

        await bot.session.close()
        logger.info("Alarm bot aiogram bot closed")

        return True
    except Exception as e:
        logger.error(f"Error stopping alarm bot: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    logger.info("Starting alarm bot as standalone...")
    try:
        asyncio.run(start_alarm_bot())
        asyncio.run(alarm_client.run_until_disconnected())
    except KeyboardInterrupt:
        logger.info("Alarm bot stopped manually.")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logger.info("Event loop closed.")
        else:
            logger.error(f"Runtime error: {e}")
    except Exception as e:
        logger.critical(
            f"Critical error during startup or execution: {e}", exc_info=True
        )
    finally:
        asyncio.run(stop_alarm_bot())
        logger.info("Alarm bot shutdown complete.")
