# %%
"""
Configurations for stripe payment
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict

# %%
class StripeSetting(BaseSettings):
    url: str
    token: str
    reservation_url: str

    model_config = SettingsConfigDict(
        env_prefix="STRIPE_",
        env_file_encoding="utf-8",
        env_file=None,
        extra="ignore"
    )

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Authorization": f"Bearer {self.token}"
        }

    def generate_payment_intent_url(self, thread_id: str, order_id: str) -> str:
        """
        Generates the payment intent URL based on thread_id and order_id.

        Args:
            thread_id: The ID of the WA thread
            order_id: orderId

        Returns:
            The constructed payment intent URL
        """
        return (
            f"{self.url}/threads/{thread_id}/orders/{order_id}/payment-url"
        )

stripe_settings = StripeSetting()
# stripe_settings