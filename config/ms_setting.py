"""
Microsoft API settings and client configuration for OrdeloAgent.
    . Defines MsSettings for Microsoft Graph API integration
    . Handles confidential client authentication and token management
    . Provides property for API request headers
    . Depends on: pydantic_settings, msal
"""

# %%
from pydantic_settings import BaseSettings, SettingsConfigDict
from msal import ConfidentialClientApplication
from aws_setting import ordelo_agent_env
from pydantic import Field


class MsSettings(BaseSettings):
    tenant_id: str = Field(..., alias="bloop_ms_tenant_id")
    client_id: str = Field(..., alias="bloop_ms_client_id")
    client_secret: str = Field(..., alias="bloop_ms_client_secret")

    @property
    def access_token(self) -> str:
        app = ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority="https://login.microsoftonline.com/common",
        )
        scope = "https://graph.microsoft.com/.default"
        result = app.acquire_token_for_client(scopes=[scope])

        if "access_token" in result:
            return result["access_token"]
        else:
            error_message = result.get("error_description", "Unknown error")
            error_code = result.get("error", "No error code available")
            print(f"Error {error_code}: {error_message}")
            raise Exception(f"Failed to obtain access token: {error_message}")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    model_config = SettingsConfigDict(extra="allow")


ms_settings = MsSettings(**ordelo_agent_env)
