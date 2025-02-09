# %%

from pydantic_settings import BaseSettings, SettingsConfigDict
import gspread
from google.oauth2.service_account import Credentials
import json
import base64
from loguru import logger

class GoogleSettings(BaseSettings):
    email: str
    encoded_credentials: str 

    model_config = SettingsConfigDict(
        env_prefix="GOOGLE_SERVICE_ACCOUNT_",
        env_file_encoding="utf-8",
        env_file=None,
        extra="ignore"
    )

    
    def get_client(self):
        # Define the scope of the API access
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Decode and load the credentials
        credentials_json = json.loads(base64.b64decode(self.encoded_credentials).decode())
        
        # Authenticate using service account
        creds = Credentials.from_service_account_info(credentials_json, scopes=SCOPES)
        
        # Connect to Google Sheets
        client = gspread.authorize(creds)
        
        return client

google_settings = GoogleSettings()
g_client = google_settings.get_client()

# %% Usage
# sheet =g_client.open("elai_takeaway_menu").sheet1
# sheet.get_all_records()

# %% How to create encoded creds
# with open(f'{project_setting.get_project_root()}/google_creds.json', "r") as file:
#     json_content = file.read()

# encoded_credentials = base64.b64encode(json_content.encode()).decode()
