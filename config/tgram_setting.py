"""
Telegram bot settings for OrdeloAgent.
    . Defines TgramBotSettings: per-bot settings read from agent_env keys `tgram_<bot_key>_*`
    . Token and webhook secret are REQUIRED: a missing or malformed value raises RuntimeError at import,
      so the service refuses to start (fail fast) instead of silently running without the bot
    . Builds aiogram Bot objects at import (no network call until the first API request)
    . Exposes the restaurant-admin bot used by channels/telegram and notebooks/telegram
    . Admin identities are NOT configured here; restaurant admins come from restaurant_master.admins
    . Depends on: pydantic_settings, aiogram, loguru, aws_setting
  Classes/Functions:
    . TgramBotSettings
    . build_bot
  Module values:
    . REST_ADMIN_BOT_KEY
    . tgram_rest_admin_settings
    . rest_admin_bot
"""

# %%
import re
from typing import Any, Mapping

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.token import TokenValidationError
from loguru import logger
from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aws_setting import agent_env

REST_ADMIN_BOT_KEY = "rest_admin"
# Telegram setWebhook secret_token rule: 1-256 chars of A-Z a-z 0-9 _ -
_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


# %%
class TgramBotSettings(BaseSettings):
    bot_key: str
    bot_token: SecretStr
    bot_username: str = ""
    webhook_secret: SecretStr
    webhook_base_url: str = ""

    model_config = SettingsConfigDict(extra="ignore")

    @field_validator("bot_username")
    @classmethod
    def _strip_at(cls, v: str) -> str:
        return v.strip().lstrip("@")

    @field_validator("webhook_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("webhook_secret")
    @classmethod
    def _check_secret(cls, v: SecretStr) -> SecretStr:
        if not _WEBHOOK_SECRET_RE.match(v.get_secret_value()):
            raise ValueError("webhook_secret must match [A-Za-z0-9_-]{1,256}")
        return v

    @property
    def path_slug(self) -> str:
        return self.bot_key.replace("_", "-")  # rest_admin -> rest-admin

    @property
    def webhook_path(self) -> str:
        return f"/telegram/{self.path_slug}/webhook"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}" if self.webhook_base_url else ""

    @classmethod
    def for_bot(cls, bot_key: str, env: Mapping[str, Any]) -> "TgramBotSettings":
        """Read `tgram_<bot_key>_*` keys from env (agent_env); empty values count as missing.

        Local env vars named TGRAM_<BOT_KEY>_* fill any gap (values from env win).
        Raises RuntimeError naming the offending keys when token or webhook secret is missing/invalid.
        """
        prefix = f"tgram_{bot_key}_"
        values = {
            k[len(prefix):]: v
            for k, v in env.items()
            if k.startswith(prefix) and v not in (None, "")
        }
        try:
            return cls(_env_prefix=prefix.upper(), bot_key=bot_key, **values)
        except ValidationError as exc:
            bad = sorted({f"{prefix}{'.'.join(map(str, e['loc']))}" for e in exc.errors()})
            raise RuntimeError(
                f"telegram[{bot_key}]: required settings missing or invalid: {', '.join(bad)} "
                f"(set them in the AWS secret or as {prefix.upper()}* environment variables)"
            ) from None


def build_bot(settings: TgramBotSettings) -> Bot:
    """Bot for the given settings. Raises RuntimeError on a malformed token (no network call)."""
    try:
        bot = Bot(
            token=settings.bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    except TokenValidationError:
        raise RuntimeError(f"telegram[{settings.bot_key}]: malformed bot token") from None
    logger.info(f"telegram[{settings.bot_key}]: configured -> {settings.webhook_path}")
    return bot


#%%
tgram_rest_admin_settings = TgramBotSettings.for_bot(REST_ADMIN_BOT_KEY, agent_env)
rest_admin_bot: Bot = build_bot(tgram_rest_admin_settings)
