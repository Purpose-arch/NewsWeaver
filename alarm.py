import asyncio
import os
import logging
import time
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Message  # Импортируем Message для type hinting
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
SOURCE_CHANNEL_ID_STR = os.getenv('SOURCE_CHANNEL_ID')
TARGET_CHANNEL_ID_STR = os.getenv('TARGET_CHANNEL_ID')
SESSION_STRING = os.getenv('SESSION_STRING')

if not all([
    API_ID, API_HASH, BOT_TOKEN, 
    SOURCE_CHANNEL_ID_STR, TARGET_CHANNEL_ID_STR,
    SESSION_STRING
]):
    logger.error("Missing one or more environment variables (API_ID, API_HASH, BOT_TOKEN, SOURCE_CHANNEL_ID, TARGET_CHANNEL_ID, SESSION_STRING). Please check your .env file.")
    exit()

try:
    API_ID = int(API_ID)
except ValueError:
    logger.error("API_ID must be an integer. Please check your .env file.")
    exit()

async def get_entity_id(client, entity_str):
    try:
        return int(entity_str)
    except ValueError:
        try:
            entity = await client.get_entity(entity_str)
            return entity.id
        except ValueError as e:
            logger.warning(f"Could not find entity '{entity_str}' using get_entity: {e}. Trying as input peer...")
            # Упрощенная логика, так как get_input_entity не всегда надежен
            logger.warning(f"Resolving '{entity_str}' as InputPeer is complex. Relying on get_entity or direct ID.")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while getting entity '{entity_str}': {e}")
            return None

bot = Bot(token=BOT_TOKEN)

# Инициализируем клиент с StringSession
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# Шаблоны сообщений для ракетной опасности
alert_message = (
    f"🔴 <b>Ракетную опасность</b> объявили на территории города Фатеж!\n\n"
    "— Проследуйте в укрытие и дождитесь окончания тревоги.\n\n"
    f"📰 <a href='https://t.me/fatezhinteresting'>Фатежский Вестник</a>"
)
off_message = (
    f"🟢 <b>Отбой ракетной опасности</b> объявлен на территории города Фатеж!\n\n"
    "— Обстановка стабилизировалась.\n\n"
    f"📰 <a href='https://t.me/fatezhinteresting'>Фатежский Вестник</a>"
)

# Новые шаблоны сообщений для опасности БПЛА
uav_alert_message = (
    f"🔴 <b>Опасность атаки БПЛА</b> объявлена на территории города Фатеж!\n\n"
    "— Соблюдайте повышенную бдительность и меры предосторожности.\n\n"
    f"📰 <a href='https://t.me/fatezhinteresting'>Фатежский Вестник</a>"
)
uav_off_message = (
    f"🟢 <b>Отбой опасности атаки БПЛА</b> дан на территории города Фатеж!\n\n"
    "— Благодарим за соблюдение мер безопасности.\n\n"
    f"📰 <a href='https://t.me/fatezhinteresting'>Фатежский Вестник</a>"
)

# Глобальное состояние
last_alert_message_id: int | None = None  # ID последнего сообщения о ракетной опасности
last_uav_alert_message_id: int | None = None  # ID последнего сообщения о БПЛА опасности
processed_events = {} # Словарь для дедупликации событий {event_hash: timestamp}
DUPLICATE_EVENT_WINDOW_SECONDS = 5 # Окно для дедупликации событий

def should_process_event(event: events.common.EventCommon) -> bool:
    """Проверяет, следует ли обрабатывать событие, используя дедупликацию."""
    global processed_events
    current_time = time.time()
    
    # Используем простой хэш события или ID сообщения, если доступно
    event_key = hash(event)
    if hasattr(event, 'message') and hasattr(event.message, 'id'):
        event_key = event.message.id # Для NewMessage и MessageEdited ID сообщения надежнее
        
    if event_key in processed_events and (current_time - processed_events[event_key] < DUPLICATE_EVENT_WINDOW_SECONDS):
        logger.warning(f"Skipping duplicate event processing for key {event_key} within {DUPLICATE_EVENT_WINDOW_SECONDS} seconds. Event type: {type(event).__name__}")
        return False
        
    processed_events[event_key] = current_time
    
    # Очистка старых записей
    cleanup_threshold = current_time - (DUPLICATE_EVENT_WINDOW_SECONDS * 10)
    keys_to_delete = [key for key, ts in processed_events.items() if ts < cleanup_threshold]
    for key in keys_to_delete:
         if key in processed_events: # Доп. проверка на случай удаления в параллельном потоке
             del processed_events[key]
             
    return True

async def send_bot_message(target_chat_id, text_to_send, original_message_id):
    """Отправляет сообщение через Aiogram бота с обработкой ошибок."""
    try:
        await bot.send_message(
            chat_id=target_chat_id,
            text=text_to_send,
            parse_mode="HTML",
            disable_web_page_preview=True,
            disable_notification=False
        )
        logger.info(f"Message based on original ID {original_message_id} sent successfully to {target_chat_id}")
    except TelegramBadRequest as e:
         logger.error(f"Failed to send message based on original ID {original_message_id} to {target_chat_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending message based on original ID {original_message_id}: {e}", exc_info=True)

async def handle_new_message(event: events.NewMessage.Event):
    """Обрабатывает только новые сообщения."""
    global last_alert_message_id, last_uav_alert_message_id
    message: Message = event.message
    
    if not should_process_event(event):
        return

    if not hasattr(message, 'text') or not message.text:
         logger.debug(f"New message {message.id} has no text, skipping.")
         return

    logger.info(f"Processing new message: ID={message.id} from chat={message.chat_id}")
    text_lower = message.text.lower()
    target_chat = TARGET_CHANNEL_ID_STR # Используем переменную из env

    # Проверка на опасность атаки БПЛА
    if "опасность атаки бпла" in text_lower:
        logger.info(f"New message {message.id} contains UAV alert phrase. Sending UAV alert and storing ID.")
        await send_bot_message(target_chat, uav_alert_message, message.id)
        last_uav_alert_message_id = message.id # Сохраняем ID сообщения о БПЛА
    # Проверка на отбой опасности БПЛА
    elif "отбой" in text_lower and "бпла" in text_lower:
        logger.info(f"New message {message.id} contains 'UAV off' phrase. Sending UAV off message and clearing UAV alert ID.")
        await send_bot_message(target_chat, uav_off_message, message.id)
        last_uav_alert_message_id = None # Сбрасываем ID при отбое
    # Проверка на ракетную опасность (ИЗМЕНЕНО)
    elif "ракетная опасность" in text_lower:
        # Избегаем срабатывания на "отбой ракетной опасности"
        if "отбой" not in text_lower:
            logger.info(f"New message {message.id} contains missile alert phrase ('ракетная опасность'). Sending missile alert and storing ID.")
            await send_bot_message(target_chat, alert_message, message.id)
            last_alert_message_id = message.id # Сохраняем ID сообщения о ракетной опасности
        else:
            logger.info(f"New message {message.id} contains 'ракетная опасность' but also 'отбой'. Assuming it is an 'off' message handled separately.")
            # Обработка отбоя ракетной опасности идет ниже
    # Проверка на отбой ракетной опасности (как было, уточнено)
    elif "отбой" in text_lower and "ракетн" in text_lower:
        logger.info(f"New message {message.id} contains 'missile off' phrase. Sending missile off message and clearing alert ID.")
        await send_bot_message(target_chat, off_message, message.id)
        last_alert_message_id = None # Сбрасываем ID при отбое
    else:
        logger.info(f"New message {message.id} does not contain target phrases. Skipping.")

async def handle_edited_message(event: events.MessageEdited.Event):
    """Обрабатывает только отредактированные сообщения, релевантные последним алертам."""
    global last_alert_message_id, last_uav_alert_message_id
    message: Message = event.message
    
    if not should_process_event(event):
        return
        
    if not hasattr(message, 'text') or not message.text:
         logger.debug(f"Edited message {message.id} now has no text, skipping.")
         return
    
    text_lower = message.text.lower()
    target_chat = TARGET_CHANNEL_ID_STR
    message_id = message.id
    
    # Обработка редактирования сообщения о ракетной опасности
    if last_alert_message_id is not None and message_id == last_alert_message_id:
        logger.info(f"Processing edit for tracked missile alert message: ID={message_id}")
        # Проверяем, появилось ли слово "отбой" в отредактированном сообщении ракетной опасности
        if "отбой" in text_lower and "ракетн" in text_lower:
            logger.info(f"Tracked missile alert message {message_id} was edited to include 'missile off' phrase. Sending missile off message.")
            await send_bot_message(target_chat, off_message, message_id)
            last_alert_message_id = None # Сбрасываем ID
        else:
            logger.debug(f"Tracked missile alert message {message_id} was edited, but does not contain 'missile off' phrase now. Skipping.")
            
    # Обработка редактирования сообщения о БПЛА опасности
    elif last_uav_alert_message_id is not None and message_id == last_uav_alert_message_id:
        logger.info(f"Processing edit for tracked UAV alert message: ID={message_id}")
        # Проверяем, появилось ли слово "отбой" в отредактированном сообщении БПЛА опасности
        if "отбой" in text_lower and "бпла" in text_lower:
            logger.info(f"Tracked UAV alert message {message_id} was edited to include 'UAV off' phrase. Sending UAV off message.")
            await send_bot_message(target_chat, uav_off_message, message_id)
            last_uav_alert_message_id = None # Сбрасываем ID
        else:
            logger.debug(f"Tracked UAV alert message {message_id} was edited, but does not contain 'UAV off' phrase now. Skipping.")
    else:
        # Если это не одно из отслеживаемых сообщений, просто игнорируем
        pass

async def main():
    global last_alert_message_id, last_uav_alert_message_id # Указываем, что будем изменять глобальные переменные
    
    async with client:
        source_entity_id = await get_entity_id(client, SOURCE_CHANNEL_ID_STR)
        if source_entity_id is None:
            logger.error(f"Could not resolve source channel: {SOURCE_CHANNEL_ID_STR}. Exiting.")
            return
        
        logger.info(f"Successfully resolved source entity: {source_entity_id}")
        logger.info(f"Target entity for Aiogram: {TARGET_CHANNEL_ID_STR}")
        
        # Регистрируем раздельные обработчики
        client.add_event_handler(handle_new_message, events.NewMessage(chats=source_entity_id))
        client.add_event_handler(handle_edited_message, events.MessageEdited(chats=source_entity_id))
        
        logger.info("Telethon client starting...")
        logger.info(f"Listening for events in source channel: {SOURCE_CHANNEL_ID_STR} (resolved ID: {source_entity_id})")
        logger.info(f"Sending custom alert/off messages to target: {TARGET_CHANNEL_ID_STR}")
        logger.info("Bot is running. Press Ctrl+C to stop.")

        await client.run_until_disconnected()

if __name__ == "__main__":
    logger.info("Starting message forwarder bot...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logger.info("Event loop closed.")
        else:
            logger.error(f"Runtime error: {e}")
    except Exception as e:
        logger.critical(f"Critical error during startup or execution: {e}", exc_info=True)
    finally:
        logger.info("Bot shutdown complete.") 