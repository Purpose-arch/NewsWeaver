# src/utils/langdock_key_gen.py
import asyncio
import json
import os
import logging
import aiohttp
from fake_headers import Headers
import pymailtm
import bs4
import re
import uuid
import random

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LANGDOCK_API_KEYS_FILE = "langdock_api_keys.json" # Путь к файлу с ключами Langdock

# Асинхронное событие для управления генерацией ключей
_key_generation_enabled_event = asyncio.Event()
_key_generation_enabled_event.set() # По умолчанию генерация включена

async def read_langdock_api_keys():
    """
    Asynchronously reads Langdock API keys from the JSON file.
    """
    # Проверяем, существует ли файл в текущей директории (utils)
    file_path = os.path.join(os.path.dirname(__file__), LANGDOCK_API_KEYS_FILE)
    if not os.path.exists(file_path):
        return {}
    try:
        f = await asyncio.to_thread(open, file_path, 'r', encoding='utf-8')
        with f:
            return json.load(f)
    except json.JSONDecodeError:
        logging.warning(f"Corrupt or empty JSON file: {file_path}. Starting with an empty dictionary.")
        return {}
    except Exception as e:
        logging.error(f"Error reading Langdock API keys file: {e}")
        return {}

async def write_langdock_api_keys(keys: dict):
    """
    Asynchronously writes Langdock API keys to the JSON file.
    """
    file_path = os.path.join(os.path.dirname(__file__), LANGDOCK_API_KEYS_FILE)
    try:
        f = await asyncio.to_thread(open, file_path, 'w', encoding='utf-8')
        with f:
            json.dump(keys, f, indent=4)
        logging.info(f"Successfully saved {len(keys)} Langdock API keys to {file_path}")
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
    """
    Fetches the CSRF token from Langdock login page.
    """
    async with session.get("https://app.langdock.com/login?redirect=%2Fchat", headers=headers) as response:
        login_page_text = await response.text()
    soup = bs4.BeautifulSoup(login_page_text, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    
    if not script or not script.string:
        raise Exception("Could not find __NEXT_DATA__ script or its content.")
        
    next_data = json.loads(script.string)
    csrf = next_data["props"]["pageProps"]["csrfToken"]
    return csrf

async def generate_langdock_api_key():
    """
    Generates a new Langdock API key.
    """
    try:
        mailtm = pymailtm.MailTm()
        head = Headers()
        headers = head.generate()
        
        account = await asyncio.to_thread(mailtm.get_account)
        address = account.address

        async with aiohttp.ClientSession(headers=headers) as session:
            csrf = await get_csrf(session, headers)

            get_email_code_payload = {"0":{"json":{"email":address,"preferMagicLink":False,"marketingFields":None},"meta":{"values":{"marketingFields":["undefined"]}}}}
            async with session.post("https://app.langdock.com/api/trpc/auth.getAuthProvider?batch=1", json=get_email_code_payload) as response:
                await response.read()

            message = await asyncio.to_thread(account.wait_for_message)

            email_code_pattern = r"[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}"
            match = re.search(email_code_pattern, message.text)
            if not match:
                raise Exception("Email code not found in message.")
            email_code = match.group()

            async with session.get(f"https://app.langdock.com/api/auth/code/callback?code={email_code}&email={address}&csrf={csrf}") as response:
                await response.read()

            workspace_name = str(uuid.uuid4())
            workspace_jobTitle = str(uuid.uuid4())
            workspace_phoneNumber = get_random_phone()
            create_workspace_payload = {"0":{"json":{"name":workspace_name,"companySize":"1-100","companyCountry":"RU","jobTitle":workspace_jobTitle,"phoneNumber":workspace_phoneNumber,"marketingFields":None},"meta":{"values":{"marketingFields":["undefined"]}}}}
            async with session.post("https://app.langdock.com/api/trpc/workspace.createOwnWorkspace?batch=1", json=create_workspace_payload) as response:
                await response.read()

            get_api_key_payload = {"0":{"json":{"name":"","expiry":"never"}}}
            async with session.post("https://app.langdock.com/api/trpc/apiKeys.createApiKey?batch=1", json=get_api_key_payload) as response:
                get_api_key_text = await response.text()
            
            api_key_json = json.loads(get_api_key_text)
            # Извлекаем ключ из json, предполагая структуру, как в apikeygen.py
            api_key = api_key_json[0]["result"]["data"]["json"]["key"]

            return api_key
    
    except Exception as e:
        logging.error(f"Error generating Langdock API key: {e}")
        return None

async def main_langdock_generator():
    """
    Main function to continuously generate and save Langdock API keys.
    """
    api_keys: dict = await read_langdock_api_keys()
    logging.info(f"Loaded {len(api_keys)} existing Langdock API keys.")

    while True:
        # Ожидаем, пока генерация не будет разрешена
        await _key_generation_enabled_event.wait()

        logging.info("Attempting to generate a new Langdock API key...")
        new_key = await generate_langdock_api_key()

        if new_key:
            if new_key not in api_keys:
                api_keys[new_key] = {"if_working": True}
                await write_langdock_api_keys(api_keys)
                logging.info(f"Generated and saved new Langdock API key: {new_key}")
            else:
                logging.info(f"Langdock API key {new_key} already exists. Skipping save.")
        else:
            logging.warning("Langdock API key generation failed. Retrying in 5 seconds...")
        
        await asyncio.sleep(5) # Wait before next attempt

if __name__ == "__main__":
    logging.info("Starting Langdock API Key Generator...")
    try:
        asyncio.run(main_langdock_generator())
    except KeyboardInterrupt:
        logging.info("Langdock API Key Generator stopped by user.")
    except Exception as e:
        logging.critical(f"An unhandled error occurred: {e}") 