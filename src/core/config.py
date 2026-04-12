import os
from typing import List, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram API
    api_id: int
    api_hash: str
    string_session: str
    bot_token: str

    # Channels
    source_ids: str = ""  # Comma-separated
    target_id: int
    moderation_chat_id: int
    source_channel_id: str = ""  # Used for alerts

    # Admins
    admin_ids: str = ""

    # LLM Settings (OpenAI Compatible)
    llm_api_key: SecretStr = Field(default=SecretStr(""))
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model_name: str = Field(default="gpt-4o-mini")

    # App Web
    web_app_url: Optional[str] = None
    port: int = 8080

    def get_source_ids(self) -> List[int]:
        if not self.source_ids:
            return []
        return [int(x.strip()) for x in self.source_ids.split(",") if x.strip()]

    def get_admin_ids(self) -> List[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip()]


settings = Settings()

# Alias common variables for backwards compatibility during refactor
API_ID = settings.api_id
API_HASH = settings.api_hash
STRING_SESSION = settings.string_session
BOT_TOKEN = settings.bot_token
MODERATION_CHAT_ID = settings.moderation_chat_id
TARGET_ID = settings.target_id
SOURCE_CHANNEL_ID = settings.source_channel_id
SOURCE_IDS = settings.get_source_ids()
ADMIN_IDS = settings.get_admin_ids()
