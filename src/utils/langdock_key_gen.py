# src/utils/langdock_key_gen.py
import asyncio
import json
import os
import logging
import aiohttp
from fake_headers import Headers
from dropmail import dropmail
import uuid
import random
import bs4
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LANGDOCK_API_KEYS_FILE = "active_langdock_api_keys.json" # Путь к файлу с активными ключами Langdock

# Асинхронное событие для управления генерацией ключей
_key_generation_enabled_event = asyncio.Event()
_key_generation_enabled_event.set() # По умолчанию генерация включена

async def read_langdock_api_keys() -> list[str]:
    """
    Asynchronously reads active Langdock API keys from the JSON file.
    """
    file_path = os.path.join(os.path.dirname(__file__), LANGDOCK_API_KEYS_FILE)
    if not os.path.exists(file_path):
        return []
    try:
        f = await asyncio.to_thread(open, file_path, 'r', encoding='utf-8')
        with f:
            data = json.load(f)
            # Ensure it's a list of strings
            if isinstance(data, list) and all(isinstance(key, str) for key in data):
                return data
            else:
                logging.warning(f"Unexpected data format in {file_path}. Starting with an empty list.")
                return []
    except json.JSONDecodeError:
        logging.warning(f"Corrupt or empty JSON file: {file_path}. Starting with an empty list.")
        return []
    except Exception as e:
        logging.error(f"Error reading Langdock API keys file: {e}")
        return []

async def write_langdock_api_keys(keys: list[str]):
    """
    Asynchronously writes active Langdock API keys to the JSON file.
    Ensures only up to two keys are stored.
    """
    file_path = os.path.join(os.path.dirname(__file__), LANGDOCK_API_KEYS_FILE)
    try:
        # Take only the first two keys
        keys_to_write = keys[:2]
        f = await asyncio.to_thread(open, file_path, 'w', encoding='utf-8')
        with f:
            json.dump(keys_to_write, f, indent=4)
        logging.info(f"Successfully saved {len(keys_to_write)} Langdock API keys to {file_path}")
    except Exception as e:
        logging.error(f"Error writing Langdock API keys to file: {e}")

def get_random_phone():
    """
    Generates a random phone number.
    """
    op_code = str(random.randint(900, 999))
    number = str(random.randint(0, 9999999)).zfill(7)
    return op_code + number

async def get_csrf(session: aiohttp.ClientSession, headers: dict) -> str:
    async with session.get("https://app.langdock.com/login?redirect=%2Fchat", headers=headers) as resp:
        text = await resp.text()
    soup = bs4.BeautifulSoup(text, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    data = json.loads(script.string)
    return data["props"]["pageProps"]["csrfToken"]

async def generate_langdock_api_key():
    """
    Generates a new Langdock API key.
    """
    mail_obj, check_messages = dropmail(wait=False)
    head = Headers()
    headers = head.generate()
    async with aiohttp.ClientSession(headers=headers) as session:
        csrf = await get_csrf(session, headers)
        payload_auth = {
            "0": {
                "json": {
                    "email": mail_obj,
                    "preferMagicLink": False,
                    "marketingFields": None
                },
                "meta": {"values": {"marketingFields": ["undefined"]}}
            }
        }
        await session.post("https://app.langdock.com/api/trpc/auth.getAuthProvider?batch=1", json=payload_auth)
        
        email_code_pattern = r"[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}"
        code = None
        for _ in range(60):
            msgs = check_messages()
            for msg in msgs:
                match = re.search(email_code_pattern, msg['text'])
                if match:
                    code = match.group()
                    break
            if code:
                break
            await asyncio.sleep(2)
        
        await session.get(f"https://app.langdock.com/api/auth/code/callback?code={code}&email={mail_obj}&csrf={csrf}")

        workspace_name = str(uuid.uuid4())
        workspace_phone = get_random_phone()
        payload_ws = {
            "0": {
                "json": {
                    "name": workspace_name,
                    "companySize": "1-100",
                    "companyCountry": "RU",
                    "jobTitle": str(uuid.uuid4()),
                    "phoneNumber": workspace_phone,
                    "marketingFields": None
                },
                "meta": {"values": {"marketingFields": ["undefined"]}}
            }
        }
        await session.post("https://app.langdock.com/api/trpc/workspace.createOwnWorkspace?batch=1", json=payload_ws)

        payload_key = {"0": {"json": {"name": "", "expiry": "never"}}}
        resp = await session.post("https://app.langdock.com/api/trpc/apiKeys.createApiKey?batch=1", json=payload_key)
        data_key = await resp.text()
        key_json = json.loads(data_key)
        api_key = key_json[0]["result"]["data"]["json"]["key"]
    return api_key

async def invalidate_and_generate_new_key(failed_key: str):
    """
    Removes a failed key from the active list and triggers generation of a new one.
    """
    logging.info(f"Invalidating key {failed_key[:4]}*** and triggering new key generation.")
    current_keys = await read_langdock_api_keys()
    updated_keys = [key for key in current_keys if key != failed_key]
    await write_langdock_api_keys(updated_keys)
    _key_generation_enabled_event.set() # Ensure generator is active to create a new key

async def main_langdock_generator():
    """
    Main function to continuously maintain exactly two active Langdock API keys.
    """
    while True:
        await _key_generation_enabled_event.wait()
        
        api_keys = await read_langdock_api_keys()
        num_active_keys = len(api_keys)
        logging.info(f"Currently {num_active_keys} active Langdock API keys.")

        if num_active_keys < 2:
            logging.info(f"Fewer than 2 active keys ({num_active_keys} found). Generating a new one...")
            new_key = await generate_langdock_api_key()
            if new_key and new_key not in api_keys:
                api_keys.append(new_key)
                await write_langdock_api_keys(api_keys)
                logging.info(f"Generated and saved new Langdock API key: {new_key}")
            elif new_key and new_key in api_keys:
                logging.info(f"Generated key {new_key} already exists. Skipping save.")
            else:
                logging.warning("Langdock API key generation failed.")
        else:
            logging.info("Two active Langdock API keys are present. Waiting for a key to be invalidated.")
            # If 2 keys exist, we can pause generation until one is marked as failed
            _key_generation_enabled_event.clear() # Pause generation until a key is invalidated

        await asyncio.sleep(5) # Check every 5 seconds

if __name__ == "__main__":
    logging.info("Starting Langdock API Key Generator...")
    try:
        asyncio.run(main_langdock_generator())
    except KeyboardInterrupt:
        logging.info("Langdock API Key Generator stopped by user.")
    except Exception as e:
        logging.critical(f"An unhandled error occurred: {e}") 