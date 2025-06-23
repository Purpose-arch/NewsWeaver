import asyncio
import aiohttp
from dropmail import dropmail
from fake_headers import Headers
import bs4
import json
import uuid
import random
import re

def get_random_phone():
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
    email, check_messages = dropmail(wait=False)
    head = Headers()
    headers = head.generate()
    async with aiohttp.ClientSession(headers=headers) as session:
        csrf = await get_csrf(session, headers)
        payload_auth = {
            "0": {
                "json": {
                    "email": email,
                    "preferMagicLink": False,
                    "marketingFields": None
                },
                "meta": {"values": {"marketingFields": ["undefined"]}}
            }
        }
        await session.post("https://app.langdock.com/api/trpc/auth.getAuthProvider?batch=1",
                           json=payload_auth)
        
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
        
        await session.get(
            f"https://app.langdock.com/api/auth/code/callback?code={code}&email={email}&csrf={csrf}"
        )

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
        await session.post("https://app.langdock.com/api/trpc/workspace.createOwnWorkspace?batch=1",
                           json=payload_ws)

        payload_key = {"0": {"json": {"name": "", "expiry": "never"}}}
        resp = await session.post("https://app.langdock.com/api/trpc/apiKeys.createApiKey?batch=1",
                                  json=payload_key)
        data_key = await resp.text()
        key_json = json.loads(data_key)
        api_key = key_json[0]["result"]["data"]["json"]["key"]
    return api_key

if __name__ == "__main__":
    key = asyncio.run(generate_langdock_api_key())
    print(key)
