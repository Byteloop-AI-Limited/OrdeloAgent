"""
Google API settings and client configuration for OrdeloAgent.
    . Defines GoogleSettings for service account and API key management
    . Provides method to instantiate gspread client for Google Sheets
    . Handles credential decoding and authentication
    . Depends on: pydantic_settings, gspread, google.oauth2, base64, json
"""

# %%
from pydantic_settings import BaseSettings, SettingsConfigDict
from aws_setting import ordelo_agent_env
from pydantic import Field
from langchain_openai import ChatOpenAI


class LLMSettings(BaseSettings):
    model: str = Field(..., alias="llm_model")
    openai_api_key: str = Field(..., alias="llm_openai_api_key")

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def llm_client(self):
        """
        Returns a ChatOpenAI instance using the model and API key from settings,
        with temperature=0, max_tokens=None, timeout=None, max_retries=2.
        """
        return ChatOpenAI(
            model=self.model,
            openai_api_key=self.openai_api_key,
            temperature=0,
            max_tokens=None,
            timeout=None,
            max_retries=2,
        )


llm_settings = LLMSettings(**ordelo_agent_env)
# %% Usage
# sheet =g_client.open("elai_takeaway_menu").sheet1
# sheet.get_all_records()

# %% How to create encoded creds
# with open(f'{project_setting.get_project_root()}/google_creds.json', "r") as file:
#     json_content = file.read()

# encoded_credentials = base64.b64encode(json_content.encode()).decode()
