# %%
"""
Configurations for project
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
from loguru import logger

# %%


def get_project_root():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)))


class ProjectSetting(BaseSettings):
    salt: str
    base_url: str

    @property
    def project_root(self) -> str:
        return get_project_root()

    model_config = SettingsConfigDict(
        env_prefix="PROJECT_SETTINGS_",
        env_file=None,
        extra="ignore"
    )


project_settings = ProjectSetting()

logger.info(f"PROJECT_ROOT is: {project_settings.project_root}")
