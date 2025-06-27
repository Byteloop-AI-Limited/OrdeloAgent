"""
Project-level configuration for OrdeloAgent.
    . Defines ProjectSetting for base settings (salt, base_url)
    . Provides get_project_root for dynamic project path resolution
    . Loads environment variables and logging
    . Depends on: os, pydantic_settings, dotenv, loguru
"""

# %%
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from aws_setting import ordelo_agent_env

# %%


def get_project_root():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)))


class ProjectSetting(BaseSettings):
    salt: str = Field(..., alias="project_settings_salt")
    base_url: str = Field(..., alias="project_settings_base_url")

    @property
    def project_root(self) -> str:
        return get_project_root()

    model_config = SettingsConfigDict(
        env_prefix="PROJECT_SETTINGS_", env_file=None, extra="allow"
    )


project_settings = ProjectSetting(**ordelo_agent_env)
