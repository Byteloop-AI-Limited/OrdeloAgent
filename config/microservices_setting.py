"""
Microservices settings and configuration for external service integrations
  . Defines MicroServicesSettings for Stripe and pricing service URLs
  . Provides authentication headers for Stripe API calls
  . Loads configuration from AWS environment settings
  . Manages bearer token authentication for microservices
  Functions/Classes:
    . MicroServicesSettings
    . ms_settings
"""

# %%

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict
from pydantic import Field

# from utils.aws_setting import env_ssm
from aws_setting import agent_env


# %%


class MicroServicesSettings(BaseSettings):
    stripe_url: str = Field(..., alias="ms_stripe_url")
    stripe_url_test: str = Field(..., alias="ms_stripe_url_test")
    stripe_token: str = Field(..., alias="ms_stripe_token")
    pricing_url: str = Field(..., alias="ms_pricing_url")

    model_config = SettingsConfigDict(extra="allow")

    @property
    def stripe_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Authorization": f"Bearer {self.stripe_token}",
        }


# ms_settings = MicroServicesSettings(**env_ssm)
ms_settings = MicroServicesSettings(**agent_env)

# %%
ms_settings.stripe_url_test
