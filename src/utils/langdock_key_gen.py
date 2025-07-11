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
TARGET_KEY_COUNT = 1 # Целевое количество активных ключей

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
            data = await asyncio.to_thread(json.load, f)
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
    Ensures only up to TARGET_KEY_COUNT keys are stored.
    """
    file_path = os.path.join(os.path.dirname(__file__), LANGDOCK_API_KEYS_FILE)
    try:
        # Take only the first TARGET_KEY_COUNT keys
        keys_to_write = keys[:TARGET_KEY_COUNT]
        f = await asyncio.to_thread(open, file_path, 'w', encoding='utf-8')
        with f:
            await asyncio.to_thread(json.dump, keys_to_write, f, indent=4)
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
    Includes retry logic for robustness.
    """
    MAX_RETRIES = 3
    RETRY_DELAY = 5 # seconds

    for attempt in range(MAX_RETRIES):
        try:
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
                for _ in range(60): # Max 120 seconds wait for email
                    msgs = await asyncio.to_thread(check_messages)
                    for msg in msgs:
                        match = re.search(email_code_pattern, msg['text'])
                        if match:
                            code = match.group()
                            break
                    if code:
                        break
                    await asyncio.sleep(2)
                
                if not code:
                    raise Exception("Timed out waiting for email code.")

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
            logging.info(f"Successfully generated new Langdock API key on attempt {attempt + 1}.")
            return api_key
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1} to generate Langdock API key failed: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
    logging.error(f"Failed to generate Langdock API key after {MAX_RETRIES} attempts.")
    return None

async def invalidate_and_generate_new_key(failed_key: str):
    """
    Removes a failed key from the active list and triggers generation of a new one.
    """
    logging.info(f"Invalidating key {failed_key[:4]}*** and triggering new key generation.")
    current_keys = await read_langdock_api_keys()
    updated_keys = [key for key in current_keys if key != failed_key]
    await write_langdock_api_keys(updated_keys)
    _key_generation_enabled_event.set() # Ensure generator is active to create a new key

async def ensure_initial_keys_generated(target_count: int = TARGET_KEY_COUNT):
    """
    Ensures that a minimum number of Langdock API keys are generated before proceeding.
    This function blocks until TARGET_KEY_COUNT keys are present.
    """
    logging.info(f"Ensuring at least {target_count} Langdock API keys are present...")
    while True:
        api_keys = await read_langdock_api_keys()
        num_active_keys = len(api_keys)
        if num_active_keys >= target_count:
            logging.info(f"Successfully ensured {num_active_keys} Langdock API keys are present.")
            break
        
        logging.info(f"Only {num_active_keys}/{target_count} keys found. Generating new key...")
        new_key = await generate_langdock_api_key()
        if new_key and new_key not in api_keys:
            api_keys.append(new_key)
            await write_langdock_api_keys(api_keys)
            logging.info(f"Generated and saved new Langdock API key: {new_key[:4]}***")
        elif new_key and new_key in api_keys:
            logging.info(f"Generated key {new_key[:4]}*** already exists. Skipping save.")
        else:
            logging.warning("Langdock API key generation failed. Retrying...")
        
        await asyncio.sleep(5) # Small delay before re-checking and generating

async def main_langdock_generator():
    """
    Main function to continuously maintain exactly TARGET_KEY_COUNT active Langdock API keys.
    This runs as a background task after initial key generation.
    """
    while True:
        await _key_generation_enabled_event.wait()
        
        api_keys = await read_langdock_api_keys()
        num_active_keys = len(api_keys)
        logging.info(f"Currently {num_active_keys} active Langdock API keys.")

        if num_active_keys < TARGET_KEY_COUNT:
            logging.info(f"Fewer than {TARGET_KEY_COUNT} active keys ({num_active_keys} found). Generating a new one...")
            new_key = await generate_langdock_api_key()
            if new_key and new_key not in api_keys:
                api_keys.append(new_key)
                await write_langdock_api_keys(api_keys)
                logging.info(f"Generated and saved new Langdock API key: {new_key[:4]}***")
            elif new_key and new_key in api_keys:
                logging.info(f"Generated key {new_key[:4]}*** already exists. Skipping save.")
            else:
                logging.warning("Langdock API key generation failed.")
        else:
            logging.info(f"{TARGET_KEY_COUNT} active Langdock API keys are present. Waiting for a key to be invalidated.")
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