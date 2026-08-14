"""Configuration for the legacy OwnTracks prompt compatibility switch."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from aws_setting import agent_env


class WaLocationSettings(BaseSettings):
    legacy_owntracks_prompts_enabled: bool = Field(
        default=False,
        alias="legacy_owntracks_prompts_enabled",
    )

    model_config = SettingsConfigDict(extra="ignore")


wa_location_settings = WaLocationSettings(**agent_env)
