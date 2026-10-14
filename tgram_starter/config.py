"""Settings from env vars (loads tgram_starter/.env_local, then .env). Deliberately independent of /config."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).parent
# load_dotenv never overrides values already set, so real env vars win, then .env_local, then .env.
load_dotenv(_HERE / ".env_local")
load_dotenv(_HERE / ".env")


def _int_list(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("TGRAM_BOT_TOKEN", ""))
    bot_username: str = field(default_factory=lambda: os.getenv("TGRAM_BOT_USERNAME", "").lstrip("@"))
    webhook_secret: str = field(default_factory=lambda: os.getenv("TGRAM_WEBHOOK_SECRET", ""))
    webhook_base_url: str = field(default_factory=lambda: os.getenv("TGRAM_WEBHOOK_BASE_URL", "").rstrip("/"))
    admin_ids: set[int] = field(default_factory=lambda: _int_list(os.getenv("TGRAM_ADMIN_IDS", "")))
    admin_api_key: str = field(default_factory=lambda: os.getenv("TGRAM_ADMIN_API_KEY", ""))
    invite_ttl_hours: int = field(default_factory=lambda: int(os.getenv("TGRAM_INVITE_TTL_HOURS", "48")))

    @property
    def webhook_path(self) -> str:
        return "/telegram/webhook"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}"


def get_settings() -> Settings:
    return Settings()
