"""
WhatsApp Business API settings for OrdeloAgent.
    . Defines WabaBusinessSettings and WabaProviderSettings for WhatsApp integration
    . Handles authentication, API tokens, and private key management
    . Provides methods for WhatsApp client instantiation (sync and async)
    . Provides WALogger class for WhatsApp-based alert logging with emoji levels
    . Depends on: pydantic_settings, pywa_async, pywa, loguru, base64, asyncio
  Classes:
    . WabaBusinessSettings
    . WabaProviderSettings
    . WALogger
    . WALogLevel
"""

# %%

import asyncio
import base64
from enum import Enum
from typing import Dict, List, Optional

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pywa import WhatsApp as WhatsAppSync
from pywa_async import WhatsApp

from aws_setting import agent_env

# from config.logger_setting import logger

# %%

# NAMESPACE = "bloopappreview"
NAMESPACE = "bloop"


class WabaBusinessSettings(BaseSettings):
    account_id: str = Field(..., alias=f"{NAMESPACE}_waa_account_id")
    token: str = Field(..., alias=f"{NAMESPACE}_waa_token")
    phone_id: int = Field(..., alias=f"{NAMESPACE}_waa_phone_id")
    callback_url: str = Field(..., alias=f"{NAMESPACE}_waa_callback_url")
    verify_token: str = Field(..., alias=f"{NAMESPACE}_waa_verify_token")
    app_id: str = Field(..., alias=f"{NAMESPACE}_waa_app_id")
    app_secret: str = Field(..., alias=f"{NAMESPACE}_waa_app_secret")
    private_key_password: str = Field(
        ..., alias=f"{NAMESPACE}_waa_private_key_password"
    )
    private_key_base64: str = Field(..., alias=f"{NAMESPACE}_waa_private_key_base64")

    model_config = SettingsConfigDict(extra="ignore")

    def create_wa(self, app=None):
        kwargs = {
            "business_account_id": self.account_id,
            "token": self.token,
            "verify_token": self.verify_token,
            "phone_id": self.phone_id,
        }
        if app is not None:
            kwargs["server"] = app
        return WhatsApp(**kwargs)

    def create_wa_sync(self):
        return WhatsAppSync(
            token=self.token,
            business_account_id=self.account_id,
            verify_token=self.verify_token,
            phone_id=self.phone_id,
        )

    @property
    def private_key(self) -> str:
        """Get the private key from the environment variable"""
        try:
            # Decode the base64 string
            decoded_bytes = base64.b64decode(self.private_key_base64)
            # Convert bytes to string (assuming PEM format needs string)
            processed_key = decoded_bytes.decode("utf-8")
            return processed_key
        except base64.binascii.Error as e:
            logger.error(f"Failed to decode base64 private key: {e}")
            return ""
        except Exception as e:
            logger.error(f"Error processing base64 private key: {e}")
            return ""

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    # @property
    # def private_key(self) -> str:
    #     """Get the private key from the config/temp_keys folder"""

    #     # Construct the path to the private key file
    #     base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    #     key_path = os.path.join(base_dir, "config", "temp_cache", "test_cde")

    #     try:
    #         with open(key_path, "r") as f:
    #             return f.read()
    #     except FileNotFoundError:
    #         logger.warning(f"Private key file not found at: {key_path}")
    #         return ""
    #     except Exception as e:
    #         logger.warning(f"Error reading private key file: {e}")
    #         return ""


# %%
waba_business_settings = WabaBusinessSettings(**agent_env)
# waba_business_settings = WabaBusinessSettings.with_env_prefix("BLOOP")
_async_wa_client = waba_business_settings.create_wa()
_sync_wa_client = waba_business_settings.create_wa_sync()
waba_business_settings.phone_id, waba_business_settings.account_id


# %

# business_phone_number = _sync_wa_client.get_business_phone_number()
# business_phone_number.verified_name, business_phone_number.webhook_configuration['whatsapp_business_account'] # Should output ('Byteloop Ai', 'https://rider-agent.ordelo.app/')

# business_phone_number = _sync_wa_client.get_business_phone_number()
# (
#     business_phone_number.verified_name,
#     business_phone_number.webhook_configuration,
# )

# %% run


# _sync_wa_client.override_waba_callback_url(
#     callback_url="https://rider-agent.ordelo.app/",
# #    callback_url="https://rider-agent-test.ordelo.app/",
#     verify_token="123456",
#     waba_id=waba_business_settings.account_id,
# )

# %%

NAMESPACE = "waba_provider"


class WabaProviderSettings(BaseSettings):
    app_id: str = Field(..., alias=f"{NAMESPACE}_app_id")
    app_secret: str = Field(..., alias=f"{NAMESPACE}_app_secret")
    configuration_id: str = Field(..., alias=f"{NAMESPACE}_configuration_id")
    graph_api_version: str = Field(..., alias=f"{NAMESPACE}_graph_api_version")
    pin: str = Field(..., alias=f"{NAMESPACE}_pin")
    token: str = Field(..., alias=f"{NAMESPACE}_token")
    business_portfolio_id: str = Field(..., alias=f"{NAMESPACE}_business_protfolio_id")

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    @property
    def graph_api_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"

    # @classmethod
    # def with_env_prefix(cls, env_prefix):
    #     config = SettingsConfigDict(
    #         env_prefix=env_prefix, env_file_encoding="utf-8", extra="ignore"
    #     )
    #     # Create a new subclass with the updated config
    #     NewClass = type(
    #         f"{cls.__name__}_{env_prefix}", (cls,), {"model_config": config}
    #     )
    #     return NewClass()


# %%

waba_provider_settings = WabaProviderSettings(**agent_env)


# %%
class WALogLevel(Enum):
    """Log levels for WhatsApp alerts with corresponding emoji icons."""

    DEBUG = "🔵"
    INFO = "ℹ️"
    CRITICAL = "🔴"
    SUCCESS = "🟢"


class WALogger:
    """
    WhatsApp-based alert logger that sends messages to a list of overwatch recipients.

    Usage:
        wa_logger = WALogger(wa=_async_wa_client, overwatch_list=["1234567890"])
        await wa_logger.debug("All looking good here")
        # Sends: "🔵 - All looking good here" to all recipients
    """

    def __init__(self, wa: WhatsApp, overwatch_list: List[str]):
        """
        Initialize WALogger.

        Args:
            wa: Async WhatsApp client instance
            overwatch_list: List of phone numbers to send alerts to
        """
        self.wa = wa
        self.overwatch_list = overwatch_list

    async def _send(
        self, level: WALogLevel, message: str, reply_to_message_id: Optional[str] = None
    ) -> None:
        """
        Internal method to send formatted alert to all overwatch recipients.

        Args:
            level: Log level determining the emoji prefix
            message: Alert message content
            reply_to_message_id: Optional message ID to reply to
        """
        formatted_text = f"{level.value} - {message}"
        tasks = [
            self.wa.send_message(
                to=recipient,
                text=formatted_text,
                reply_to_message_id=reply_to_message_id,
            )
            for recipient in self.overwatch_list
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def debug(
        self, message: str, reply_to_message_id: Optional[str] = None
    ) -> None:
        """Send a debug level alert (🔵)."""
        await self._send(WALogLevel.DEBUG, message, reply_to_message_id)

    async def info(
        self, message: str, reply_to_message_id: Optional[str] = None
    ) -> None:
        """Send an info level alert (ℹ️)."""
        await self._send(WALogLevel.INFO, message, reply_to_message_id)

    async def critical(
        self, message: str, reply_to_message_id: Optional[str] = None
    ) -> None:
        """Send a critical level alert (🔴)."""
        await self._send(WALogLevel.CRITICAL, message, reply_to_message_id)

    async def success(
        self, message: str, reply_to_message_id: Optional[str] = None
    ) -> None:
        """Send a success level alert (🟢)."""
        await self._send(WALogLevel.SUCCESS, message, reply_to_message_id)


# %%

# await wa_logger.debug("All looking good here")
# await wa_logger.critical("Database connection failed")
