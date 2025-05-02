# moderation.py
import asyncio
from telethon import Button, events
import config
import clients
import publisher
from logger import logger

# pending[(channel_id, message_id)] = {"client":…, "message":…, "text":…, "decided":…}
pending: dict[tuple[int,int], dict] = {}

async def send_for_moderation(channel_id: int, message_id: int, text: str, client, original_message):
    """
    Рассылает переформулированный текст всем ADMIN_IDS с Inline-кнопками.
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
        await clients.bot_client.send_message(
            admin, text, buttons=buttons, parse_mode='HTML'
        )
    logger.info(f"Sent to moderation {key}")
    # Автоматическое отклонение через 24 часа
    asyncio.create_task(_auto_reject(key, 24*3600))

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

        logger.info(f"Moderator {event.sender_id} - {action} {key}")