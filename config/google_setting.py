"""
Google API settings and client configuration for OrdeloAgent.
    . Defines GoogleSettings for service account and API key management
    . Provides method to instantiate gspread client for Google Sheets
    . Handles credential decoding and authentication
    . Depends on: pydantic_settings, gspread, google.oauth2, base64, json
"""

# %%
from pydantic_settings import BaseSettings, SettingsConfigDict
# import gspread
from google.oauth2.service_account import Credentials
import json
import base64
from aws_setting import ordelo_agent_env
from pydantic import Field


class GoogleSettings(BaseSettings):
    email: str = Field(..., alias="google_service_account_email")
    encoded_credentials: str = Field(
        ..., alias="google_service_account_encoded_credentials"
    )
    maps_api_key: str = Field(..., alias="google_service_account_maps_api_key")

    model_config = SettingsConfigDict(extra="allow")

    def get_client(self):
        # Define the scope of the API access
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        # Decode and load the credentials
        credentials_json = json.loads(
            base64.b64decode(self.encoded_credentials).decode()
        )

        # Authenticate using service account
        creds = Credentials.from_service_account_info(credentials_json, scopes=SCOPES)

        # Connect to Google Sheets
        # client = gspread.authorize(creds)
        client = None

        return client


google_settings = GoogleSettings(**ordelo_agent_env)
g_client = google_settings.get_client()

# %% Usage
# sheet =g_client.open("elai_takeaway_menu").sheet1
# sheet.get_all_records()

# %% How to create encoded creds
# with open(f'{project_setting.get_project_root()}/google_creds.json', "r") as file:
#     json_content = file.read()

# encoded_credentials = base64.b64encode(json_content.encode()).decode()
