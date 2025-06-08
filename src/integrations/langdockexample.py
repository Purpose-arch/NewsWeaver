import httpx

url = "https://api.langdock.com/assistant/v1/chat/completions"

payload = {
    "assistant": {
        "name": "Cody",
        "instructions": "Ты - Cody, помощник по программированию. Отвечай на вопросы по коду и помогай с программированием.",
        "temperature": 0.7,
        "model": "o3",
        "capabilities": {}
    },
    "messages": [
        {
            "role": "user",
            "content": "Привет",
        }
    ]
}

headers = {
    "Authorization": "Bearer <api_key>",
    "Content-Type": "application/json"
}

response = httpx.post(url, json=payload, headers=headers)

print(response.text)