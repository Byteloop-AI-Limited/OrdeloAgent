"""
FoodOrder pydantic model for food_order table
  . Depends on pydantic, config, and utils_common.pricing_ms
  . Provides model for food order records
  . Supports fetching from DB by order_id
  . Supports updating final order value and bubbles failures to the caller
  . Now supports generating a capture payload for payment processing
  . On instantiation via from_order_id, ensures final_order_value is up-to-date
  . Provides a payment_uri property to generate payment URL for Stripe
Functions/Classes:
  . FoodOrder
    . get_final_order_value
    . from_order_id
    . update_final_order_value
    . gen_capture_payload
    . generate_order_summary_for_payment_intent
    . generate_order_summary_for_automatic_payment
    . payment_uri (property)
    . gen_payment_intent_payload
"""

# %%
from typing import Optional
import requests
from pydantic import BaseModel
from config import client_ordelo, logger, ms_settings
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster


# %%


class FoodOrder(BaseModel):
    """Pydantic model representing the food_order table."""

    order_id: str
    order_number: str
    seq_id: Optional[int] = None
    recipient: str
    notes: Optional[str] = None
    thread_id: str
    action: str
    total_price: float
    final_order_value: Optional[float] = None
    rest_cost: Optional[float] = None
    service_charge: Optional[float] = None
    delivery_fee: Optional[float] = None
    small_order_fee: Optional[float] = None
    commission_rate: Optional[float] = None
    payment_status: str

    @staticmethod
    def get_final_order_value(
        order_number: str, cust_lat: float, cust_lon: float, total_food_value: float
    ):
        """
        Calculates final order value by calling the pricing microservice.

        Args:
            order_number: The order number.
            cust_lat: Customer latitude.
            cust_lon: Customer longitude.
            total_food_value: Total food value before fees.

        Returns:
            dict: Pricing option for car delivery, or tuple (status_code, text) on error.
        """
        rest_ref = order_number.split("-")[0]
        rest_master = RestaurantMaster.from_rest_ref(rest_ref)

        payload = {
            "order_number": order_number,
            "total_food_value": total_food_value,
            "restaurant_latitude": rest_master.lat,
            "restaurant_longitude": rest_master.lon,
            "customer_latitude": cust_lat,
            "customer_longitude": cust_lon,
        }
        url = ms_settings.pricing_url
        headers = {"Content-Type": "application/json"}

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            return response.status_code, response.text
        response_json = response.json()

        option = {}
        for option in response_json["delivery_options"]:
            if option["vehicle_type"] == "car":
                option = option
                break

        return option

    @classmethod
    def from_order_number(cls, order_number: str) -> Optional["FoodOrder"]:
        """
        Fetches food order data from the database using the order_id
        and returns a FoodOrder instance.

        Args:
            client: The database client (e.g., Supabase client).
            order_id: The ID of the order to fetch.

        Returns:
            A FoodOrder instance if the order is found, otherwise None.
        """
        try:
            food_order_row = (
                client_ordelo.table("food_order")
                .select("*")
                .eq("order_number", order_number)
                .execute()
                .data[0]
            )
            instance = cls(**food_order_row)
            if instance.final_order_value is None and instance.action == "delivery":
                updated = instance.update_final_order_value_in_db()
                if not updated:
                    logger.error(
                        "FoodOrder.from_order_number: failed to update final order value for %s",
                        order_number,
                    )
                    return None
            return instance
        except (
            IndexError,
            Exception,
        ) as e:  # Catch potential errors like no data found or DB connection issues
            logger.error(f"Error fetching order {order_number}: {e}")
            return None

    @classmethod
    def from_order_id(cls, order_id: str) -> Optional["FoodOrder"]:
        """
        Fetches food order data from the database using the order_id
        and returns a FoodOrder instance.

        Args:
            client: The database client (e.g., Supabase client).
            order_id: The ID of the order to fetch.

        Returns:
            A FoodOrder instance if the order is found, otherwise None.
        """
        try:
            food_order_row = (
                client_ordelo.table("food_order")
                .select("*")
                .eq("order_id", order_id)
                .execute()
                .data[0]
            )
            instance = cls(**food_order_row)
            if instance.final_order_value is None and instance.action == "delivery":
                updated = instance.update_final_order_value_in_db()
                if not updated:
                    logger.error(
                        "FoodOrder.from_order_id: failed to update final order value for %s",
                        order_id,
                    )
                    return None
            return instance
        except (
            IndexError,
            Exception,
        ) as e:  # Catch potential errors like no data found or DB connection issues
            logger.error(f"Error fetching order {order_id}: {e}")
            return None

    @property
    def payment_uri(self) -> str:
        """
        Generates the payment URL for this order using order_id and thread_id.

        Returns:
            str: The constructed payment URL for this order.
        """
        return f"{ms_settings.stripe_url}/threads/{self.thread_id}/orders/{self.order_id}/payment-url"

    def update_final_order_value_in_db(self) -> bool:
        """
        Calculates the final order value, including charges and fees,
        updates the database record, and updates the instance attributes.

        Args:
            client: The main database client (for updating food_order).
            client_ordelo: The database client for accessing customer_master_new.

        Returns:
            True if the update was successful, False otherwise.
        """
        try:
            # 1. Fetch customer data
            customer_master_row = (
                client_ordelo.table("customer_master")
                .select("lat, lon")
                .eq("cust_id", self.recipient)
                .single()
                .execute()
                .data
            )
            if not customer_master_row:
                logger.error(
                    f"Error: Customer not found for recipient {self.recipient}"
                )
                return False

            # 2. Calculate pricing #ToDo - check if the pricingPl returns a msg (str) with min_order_value
            pricing_pl: dict = self.get_final_order_value(
                order_number=self.order_number,
                cust_lat=customer_master_row["lat"],
                cust_lon=customer_master_row["lon"],
                total_food_value=self.total_price,  # Use self.total_price
            )

            if not isinstance(pricing_pl, dict):
                logger.error(
                    f"Error: Pricing response is not a dictionary for order {self.order_id}. Pricing response: {pricing_pl}"
                )
                return False

            # 3. Prepare update data
            food_order_update = {
                "final_order_value": pricing_pl["final_order_value"],
                "rest_cost": pricing_pl["rest_cost"],
                "service_charge": pricing_pl["breakdown"]["service_charge"],
                "delivery_fee": pricing_pl["breakdown"].get("delivery_fee"),
                "small_order_fee": pricing_pl["breakdown"].get("small_order_fee"),
                "commission_rate": pricing_pl["breakdown"].get("commission_rate"),
            }
            # Filter out None values if the DB schema doesn't handle them well for updates
            # food_order_update = {k: v for k, v in food_order_update.items() if v is not None}

            # 4. Update database
            update_response = (
                client_ordelo.table("food_order")
                .update(food_order_update)
                .eq("order_id", self.order_id)
                .execute()
            )

            # Optional: Check response if needed, supabase-py returns APIResponse with data/error

            # 5. Update instance attributes on success
            self.final_order_value = food_order_update.get("final_order_value")
            self.rest_cost = food_order_update.get("rest_cost")
            self.service_charge = food_order_update.get("service_charge")
            self.delivery_fee = food_order_update.get("delivery_fee")
            self.small_order_fee = food_order_update.get("small_order_fee")
            self.commission_rate = food_order_update.get("commission_rate")
            logger.info(
                f"Successfully updated final order value for order {self.order_id}"
            )
            return True

        except Exception as e:
            logger.error(
                f"Error updating final order value for order {self.order_id}: {e}"
            )
            return False

    async def gen_capture_payload(self) -> dict:
        """
        Generates a dictionary payload for payment capture action.

        Returns:
            dict: A payload with action, payment_mode, rest_payout, and total_amount.
        """
        order_summary = await self.generate_order_summary_for_payment_intent()
        return {
            "items": order_summary.get("items"),
            "action": self.action,
            "payment_mode": "capture",
            "rest_payout": self.rest_cost,
            "total_amount": self.final_order_value,
            "notes": self.notes,
        }

    async def generate_order_summary_for_payment_intent(self) -> dict:
        """
        Generates an order summary dictionary for payment intent, including product and fee items.

        Returns:
            dict: Order summary with all items for payment intent.
        """
        order_items = (
            client_ordelo.table("order_item")
            .select("""
                product_name, 
                quantity, 
                price
            """)
            .eq("order_id", self.order_id)
            .execute()
        )

        fee_items = [
            {
                "product_name": "Service Charge",
                "quantity": 1,
                "price": self.service_charge,
            },
            {
                "product_name": "Delivery Fee",
                "quantity": 1,
                "price": self.delivery_fee,
            },
            {
                "product_name": "Small Order Fee",
                "quantity": 1,
                "price": self.small_order_fee,
            },
        ]

        # Filter out fees with a price of 0 or None
        fee_items = [item for item in fee_items if item["price"] and item["price"] > 0]
        all_items = order_items.data + fee_items
        order_summary = {"items": all_items}
        return order_summary

    async def generate_order_summary_for_automatic_payment(self) -> dict:
        """
        Generates an order summary dictionary for automatic payment capture.
        Only includes order items without any additional fees (no service charge,
        delivery fee, or small order fee).

        Returns:
            dict: Order summary with only product items for automatic payment.
        """
        order_items = (
            client_ordelo.table("order_item")
            .select("""
                product_name, 
                quantity, 
                price
            """)
            .eq("order_id", self.order_id)
            .execute()
        )

        order_summary = {"items": order_items.data}
        return order_summary

    async def gen_payment_intent_payload(self) -> dict:
        """
        Generates the payload dictionary for a Stripe payment intent for this order.

        Returns:
            dict: The intent payload for Stripe payment intent creation.
        """
        order_summary = await self.generate_order_summary_for_payment_intent()
        intent_payload = {
            "items": order_summary.get("items"),
            "currency": "GBP",
            "action": "delivery",
            "manual_mode_capture": True,
            "notes": self.notes,
        }
        return intent_payload


# %%

# if __name__ == "__main__":
#     # food_order = FoodOrder.from_order_id("TDOJ-39")
#     food_order = FoodOrder.from_order_number("ELAS-ZVEO-29")
#     # op = await food_order.generate_order_summary_for_automatic_payment()
#     op = await food_order.generate_order_summary_for_payment_intent()
#     print(op, food_order)
