# moderation.py
import asyncio
import os
import json
import shutil
import tempfile
from telethon import Button, events
import src.core.config as config
import src.core.clients as clients
import src.features.publisher as publisher
import src.utils.media as media
import src.integrations.requesty as requesty
import src.integrations.llm as llm
import requests
from typing import Optional, Union, List
from src.core.logger import logger
import src.features.direct_news as direct_news


TEMP_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_media")
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

pending = {}


async def send_for_moderation(
    channel_id: int,
    message_id: int,
    text: str,
    client,
    original_message,
    source_type: str = "telegram",
):
    """
    Places a news message into the in-memory moderation queue and sends it to MODERATION_CHAT_ID with accept/reject buttons.

    Args:
        channel_id: Source channel or chat ID.
        message_id: Original message ID from the source.
        text: Reformulated or checked news text.
        client: Telethon client instance that received the message.
        original_message: The original message object from the source.
        source_type: Source type ("telegram" or "vk").
    """
    key = (channel_id, message_id)

    if key in pending:
        logger.warning(f"Message {key} already pending for moderation")
        return

    pending[key] = {
        "text": text,
        "client": client,
        "message": original_message,
        "decided": None,
        "moderation_msg_ids": [],
        "source_type": source_type,
        "media_paths": [],
    }

    buttons = [
        [
            Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
            Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}"),
        ]
    ]

    try:
        if source_type == "telegram" and hasattr(original_message, "media"):
            grouped_id = getattr(original_message, "grouped_id", None)

            message_dir = os.path.join(TEMP_MEDIA_DIR, f"tg_{channel_id}_{message_id}")
            os.makedirs(message_dir, exist_ok=True)

            has_media = True
            media_paths = []

            if grouped_id:
                entity = getattr(original_message, "chat_id", None) or getattr(
                    original_message.peer_id, "channel_id", None
                )
                msgs = await client.get_messages(
                    entity, limit=100
                )
                media_msgs = [
                    m for m in msgs if getattr(m, "grouped_id", None) == grouped_id
                ]
                media_msgs.sort(key=lambda m: m.id)

                for msg in media_msgs:
                    if hasattr(msg, "media"):
                        path = await client.download_media(msg, file=message_dir)
                        if path:
                            media_paths.append(path)
            else:
                path = await client.download_media(original_message, file=message_dir)
                if path:
                    media_paths.append(path)
                else:
                    has_media = False

            pending[key]["media_paths"] = media_paths

            if has_media and media_paths:
                if len(media_paths) > 1:
                    album_msgs = await clients.bot_client.send_file(
                        config.MODERATION_CHAT_ID, media_paths, parse_mode="HTML"
                    )

                    if isinstance(album_msgs, list):
                        for msg in album_msgs:
                            if hasattr(msg, "id"):
                                pending[key]["moderation_msg_ids"].append(msg.id)
                    elif hasattr(album_msgs, "id"):
                        pending[key]["moderation_msg_ids"].append(album_msgs.id)

                    text_msg = await clients.bot_client.send_message(
                        config.MODERATION_CHAT_ID,
                        text,
                        buttons=buttons,
                        parse_mode="HTML",
                    )
                    if text_msg:
                        pending[key]["moderation_msg_ids"].append(text_msg.id)
                else:
                    msg = await clients.bot_client.send_file(
                        config.MODERATION_CHAT_ID,
                        media_paths[0],
                        caption=text,
                        buttons=buttons,
                        parse_mode="HTML",
                    )
                    if msg:
                        pending[key]["moderation_msg_ids"].append(msg.id)
            else:
                msg = await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID, text, buttons=buttons, parse_mode="HTML"
                )
                if msg:
                    pending[key]["moderation_msg_ids"].append(msg.id)
        else:
            msg = await clients.bot_client.send_message(
                config.MODERATION_CHAT_ID, text, buttons=buttons, parse_mode="HTML"
            )
            if msg:
                pending[key]["moderation_msg_ids"].append(msg.id)

    except Exception as e:
        logger.error(f"Failed to send message to moderation chat: {e}")

    logger.info(f"Sent to moderation chat {key} (source: {source_type})")


async def regenerate_with_custom_prompt(entry, custom_prompt, replied_msg_id):
    """
    Regenerates news using a custom prompt and sends it to the moderation chat.
    """
    try:
        original_text = entry["text"]
        new_text = await llm.modify_text_with_custom_prompt(
            original_text, custom_prompt
        )

        if not new_text:
            logger.error("Failed to regenerate text with custom prompt")
            return False

        entry["text"] = new_text

        try:
            msg_ids_to_delete = entry["moderation_msg_ids"].copy()
            if msg_ids_to_delete:
                logger.info(
                    f"Deleting {len(msg_ids_to_delete)} messages from moderation chat"
                )
                try:
                    await clients.bot_client.delete_messages(
                        config.MODERATION_CHAT_ID, msg_ids_to_delete
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to bulk delete messages: {e}, trying one by one"
                    )
                    for msg_id in msg_ids_to_delete:
                        try:
                            await clients.bot_client.delete_messages(
                                config.MODERATION_CHAT_ID, msg_id
                            )
                            await asyncio.sleep(
                                0.2
                            )
                        except Exception as msg_e:
                            logger.warning(f"Cannot delete message {msg_id}: {msg_e}")

                entry["moderation_msg_ids"] = []
        except Exception as e:
            logger.warning(f"Error deleting moderation messages: {e}")

        channel_id, message_id = next(
            (k for k, v in pending.items() if v == entry), (None, None)
        )
        if not channel_id or not message_id:
            logger.error("Cannot find key for entry")
            return False

        source_type = entry.get("source_type", "telegram")

        buttons = [
            [
                Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
                Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}"),
            ]
        ]

        if entry.get("media_paths"):
            if len(entry["media_paths"]) > 1:
                album_msgs = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID, entry["media_paths"], parse_mode="HTML"
                )

                if isinstance(album_msgs, list):
                    for msg in album_msgs:
                        if hasattr(msg, "id"):
                            entry["moderation_msg_ids"].append(msg.id)
                elif hasattr(album_msgs, "id"):
                    entry["moderation_msg_ids"].append(album_msgs.id)

                text_msg = await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    new_text,
                    buttons=buttons,
                    parse_mode="HTML",
                )
                if text_msg:
                    entry["moderation_msg_ids"].append(text_msg.id)
            else:
                msg = await clients.bot_client.send_file(
                    config.MODERATION_CHAT_ID,
                    entry["media_paths"][0],
                    caption=new_text,
                    parse_mode="HTML",
                    buttons=buttons,
                )
                if msg:
                    entry["moderation_msg_ids"].append(msg.id)
        else:
            msg = await clients.bot_client.send_message(
                config.MODERATION_CHAT_ID, new_text, buttons=buttons, parse_mode="HTML"
            )
            if msg:
                entry["moderation_msg_ids"].append(msg.id)

        logger.info(
            f"Regenerated news with custom prompt for {channel_id}:{message_id} (source: {source_type})"
        )
        return True
    except Exception as e:
        logger.error(f"Error regenerating with custom prompt: {e}")
        return False


async def register_handlers():
    """
    Registers the CallbackQuery handler on the bot client.
    """

    @clients.bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode()

        if data.startswith("direct_"):
            if await direct_news.process_direct_callback(event):
                return

        action, ch, mid = data.split(":")
        key = (int(ch), int(mid))
        entry = pending.get(key)

        if not entry:
            await event.answer("Срок истёк или нет данных", alert=True)
            return
        if entry["decided"]:
            await event.answer("Уже обработано", alert=True)
            return

        entry["decided"] = action
        if action == "accept":
            await publisher.publish(*key, entry.get("source_type", "telegram"))
            await event.answer("✅ Принято", alert=False)
        else:
            await publisher.reject(*key, entry.get("source_type", "telegram"))
            await event.answer("❌ Отклонено", alert=False)

        try:
            msg_ids = entry.get("moderation_msg_ids", [])
            logger.info(
                f"Attempting to delete {len(msg_ids)} moderation messages: {msg_ids}"
            )

            if msg_ids:
                try:
                    await clients.bot_client.delete_messages(
                        config.MODERATION_CHAT_ID, msg_ids
                    )
                except Exception as bulk_delete_error:
                    logger.warning(
                        f"Failed to bulk delete messages, will try one by one: {bulk_delete_error}"
                    )
                    for msg_id in msg_ids:
                        try:
                            await clients.bot_client.delete_messages(
                                config.MODERATION_CHAT_ID, msg_id
                            )
                            await asyncio.sleep(
                                0.2
                            )
                        except Exception as msg_delete_error:
                            logger.warning(
                                f"Cannot delete moderation message {msg_id}: {msg_delete_error}"
                            )

            try:
                if hasattr(event, "message") and event.message and event.message.id:
                    await event.delete()
            except Exception as e:
                logger.warning(f"Error while deleting moderation messages: {e}")
        except Exception as e:
            logger.warning(f"Error while deleting moderation messages: {e}")

        logger.info(
            f"Moderator {event.sender_id} - {action} {key} (source: {entry.get('source_type', 'telegram')})"
        )

    @clients.bot_client.on(
        events.NewMessage(chats=config.MODERATION_CHAT_ID, func=lambda e: e.is_reply)
    )
    async def custom_prompt_handler(event):
        try:
            replied_msg = await event.get_reply_message()
            if not replied_msg:
                return

            msg_id = replied_msg.id
            found_entry = None
            found_key = None

            for key, entry in pending.items():
                if (
                    msg_id in entry.get("moderation_msg_ids", [])
                    and not entry["decided"]
                ):
                    found_entry = entry
                    found_key = key
                    break

            if not found_entry:
                return

            custom_prompt = event.text.strip()
            if not custom_prompt:
                return

            try:
                await event.delete()
            except Exception as e:
                logger.warning(f"Cannot delete custom prompt message: {e}")

            channel_id, message_id = found_key
            logger.info(
                f"Regenerating news {channel_id}:{message_id} with custom prompt: {custom_prompt}"
            )

            success = await regenerate_with_custom_prompt(
                found_entry, custom_prompt, replied_msg.id
            )
            if not success:
                await clients.bot_client.send_message(
                    config.MODERATION_CHAT_ID,
                    f"❌ Не удалось регенерировать новость с промптом:\n<code>{custom_prompt}</code>",
                    parse_mode="HTML",
                    reply_to=replied_msg.id,
                )

        except Exception as e:
            logger.error(f"Error in custom prompt handler: {e}")

    @clients.bot_client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        sender_id = event.sender_id
        if sender_id not in config.ADMIN_IDS:
            await event.reply("иди нахуй долбоеб")
            logger.warning(f"Unauthorized /start command from user ID: {sender_id}")
            return
        logger.info(f"Admin {sender_id} used /start command.")

    await direct_news.register_handlers()


def cleanup_media_files(key):
    """
    Cleans up downloaded media files for the given key.
    """
    channel_id, message_id = key
    message_dir = os.path.join(TEMP_MEDIA_DIR, f"{channel_id}_{message_id}")
    if os.path.exists(message_dir):
        try:
            shutil.rmtree(message_dir)
            logger.info(f"Cleaned up media files for {key}")
        except Exception as e:
            logger.warning(f"Error cleaning up media files for {key}: {e}")
