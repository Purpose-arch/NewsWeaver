# moderation.py
import asyncio
from telethon import Button, events
import config
import clients
import publisher
import media
import tempfile
from logger import logger

# pending[(channel_id, message_id)] = {"client":…, "message":…, "text":…, "decided":…}
pending: dict[tuple[int,int], dict] = {}

async def send_for_moderation(channel_id: int, message_id: int, text: str, client, original_message):
    """
    Рассылает переформулированный текст и вложения всем ADMIN_IDS с Inline-кнопками.
    Решение фиксируется — повторные клики игнорируем.
    """
    key = (channel_id, message_id)
    pending[key] = {
        "client": client,
        "message": original_message,
        "text": text,
        "decided": False
    }

    buttons = [
        [
            Button.inline("✅ Принять", f"accept:{channel_id}:{message_id}"),
            Button.inline("❌ Отклонить", f"reject:{channel_id}:{message_id}")
        ]
    ]
    for admin in config.ADMIN_IDS:
        # send media with caption and inline buttons in one message
        if getattr(original_message, 'media', None):
            grouped_id = getattr(original_message, 'grouped_id', None)
            entity = getattr(original_message, 'chat_id', None) or getattr(original_message.peer_id, 'channel_id', None)
            try:
                if grouped_id:
                     # If it's an album, try sending directly first (might work for bots sometimes)
                     # Note: Telethon's send_file might not directly support sending existing media objects as an album.
                     # We rely on the fallback mechanism (download & re-upload) for guaranteed album delivery.
                     # Attempting direct send first as an optimization, though likely to fail and trigger fallback.
                     # Fetch messages to get the media list - this might be redundant if direct send fails,
                     # but needed if we wanted to *attempt* direct send with multiple media objects (which isn't standard API)
                     msgs = await client.get_messages(entity, limit=100) # Use original client here
                     media_msgs_in_group = [m for m in msgs if getattr(m, 'grouped_id', None) == grouped_id and m.media]
                     media_msgs_in_group.sort(key=lambda m: m.id)
                     # This direct send of multiple media objects is unlikely to work as intended via send_file for albums
                     # await clients.bot_client.send_file(admin, media_to_send, caption=text, parse_mode='HTML', buttons=buttons)
                     # Force fallback for albums for now, as direct send_file with list of media objects isn't reliable
                     raise ValueError("Force fallback for album handling")
                else:
                    # Try sending single media directly
                    await clients.bot_client.send_file(
                        admin,
                        original_message.media, # Use the original media object
                        caption=text,
                        parse_mode='HTML',
                        buttons=buttons
                    )
            except Exception as e:
                logger.warning(f"Direct send failed for admin {admin}: {e}, fallback to download")
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        if grouped_id:
                            # Fetch messages again or reuse if available
                            if 'media_msgs_in_group' not in locals(): # Ensure we have the list
                                msgs = await client.get_messages(entity, limit=100) # Use original client
                                media_msgs_in_group = [m for m in msgs if getattr(m, 'grouped_id', None) == grouped_id and m.media]
                                media_msgs_in_group.sort(key=lambda m: m.id)

                            # Download all media from the album using the original client
                            paths = await client.download_media(media_msgs_in_group, file=tmp)
                            # Send downloaded files as an album via bot client
                            await clients.bot_client.send_file(
                                admin,
                                paths, # Send the list of paths
                                caption=text,
                                parse_mode='HTML',
                                buttons=buttons
                            )
                        else:
                            # Fallback for single media: download via original client and resend via bot
                            path = await client.download_media(original_message, file=tmp) # Use original client
                            await clients.bot_client.send_file(
                                admin,
                                path,
                                caption=text,
                                parse_mode='HTML',
                                buttons=buttons
                            )
                    except Exception as download_send_e:
                        logger.error(f"Fallback download/send failed for admin {admin} on {key}: {download_send_e}")

        else:
            # если медиа нет, просто отправляем текст с кнопками
            await clients.bot_client.send_message(
                admin,
                text,
                buttons=buttons,
                parse_mode='HTML'
            )

    logger.info(f"Sent to moderation {key}")
    # schedule automatic rejection after 24 hours
    asyncio.create_task(_auto_reject(key, 24 * 3600))

async def _auto_reject(key, delay: int):
    await asyncio.sleep(delay)
    entry = pending.get(key)
    if entry and not entry["decided"]:
        entry["decided"] = "reject"
        await publisher.reject(*key)
        logger.info(f"Auto-rejected {key}")

async def register_handlers():
    """
    Регистрируем CallbackQuery обработчик на бот-клиенте.
    """
    @clients.bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode()
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
            await publisher.publish(*key)
            await event.answer("✅ Принято", alert=False)
        else:
            await publisher.reject(*key)
            await event.answer("❌ Отклонено", alert=False)

        # delete the moderation message after processing
        try:
            await event.delete()
        except Exception as e:
            logger.warning(f"Cannot delete moderation message: {e}")

        logger.info(f"Moderator {event.sender_id} - {action} {key}")