"""
Project-level configuration for OrdeloAgent.
    . Defines ProjectSetting for base settings (salt, base_url)
    . Provides get_project_root for dynamic project path resolution
    . Loads environment variables and logging
    . Depends on: os, pydantic_settings, dotenv, loguru
"""

# %%
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)
from pydantic import Field
from aws_setting import ordelo_agent_env
import json

# %%


class ProjectSetting(BaseSettings):
    salt: str = Field(..., alias="project_settings_salt")
    base_url: str = Field(..., alias="project_settings_base_url")

    model_config = SettingsConfigDict(extra="allow")


# Then just instantiate:
settings = ProjectSetting(**ordelo_agent_env)
# settings = ProjectSetting.model_validate_json(secrets)
print(settings.salt)
print(settings.base_url)
# %%
import os
from pydantic_settings import AWSSecretsManagerSettingsSource


class ProjectSetting(BaseSettings):
    project_settings_salt: str
    project_settings_base_url: str

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,  # you won’t use this
        env_settings,  # nor this
        dotenv_settings,  # nor this
        file_secret_settings,  # nor this
    ):
        secret_id = os.environ["AWS_SECRETS_MANAGER_SECRET_ID"]
        print(secret_id)
        return (AWSSecretsManagerSettingsSource(settings_cls, secret_id),)


# usage
settings = ProjectSetting()
print(settings.project_settings_salt)
print(settings.project_settings_base_url)
