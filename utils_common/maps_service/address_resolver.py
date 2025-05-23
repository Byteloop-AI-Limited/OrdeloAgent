# %%
"""
Resolve addresses using Google Geocoding API
    . Uses Google Maps Geocoding API to convert addresses into geocode data
    . Defines Pydantic models for API response components
    . Provides functions to fetch geocode results and extract formatted addresses
"""

import requests
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
import logging
from config import google_settings

API_KEY = google_settings.maps_api_key

# %%
# Set up logging
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


class AddressComponent(BaseModel):
    """Model for individual address components from Google Geocoding API"""

    long_name: str
    short_name: str
    types: List[str]


class GeocodeResult(BaseModel):
    """Model for a single geocode result from Google Geocoding API"""

    address_components: List[AddressComponent]
    formatted_address: str
    place_id: str
    types: List[str]
    geometry: Dict[str, Any]


class GeocodeResponse(BaseModel):
    """Model for the full response from Google Geocoding API"""

    results: List[GeocodeResult]
    status: str


class UKAddress(BaseModel):
    """Pydantic model for a UK address"""

    house_number: Optional[str] = Field(None, description="House/Flat Number or Name")
    building_name: Optional[str] = Field(
        None, description="Building Name (if applicable)"
    )
    street_name: Optional[str] = Field(None, description="Street Name")
    locality: Optional[str] = Field(None, description="Locality or district")
    city: Optional[str] = Field(None, description="Town/City")
    county: Optional[str] = Field(None, description="County")
    postcode: Optional[str] = Field(None, description="Postcode")
    country: str = Field("United Kingdom", description="Country")

    # Original data used for resolution
    latitude: Optional[float] = Field(None, description="Latitude used for geocoding")
    longitude: Optional[float] = Field(None, description="Longitude used for geocoding")
    input_postcode: Optional[str] = Field(
        None, description="Postcode used for geocoding"
    )

    # Raw API response data
    raw_response: Optional[Dict[str, Any]] = Field(
        None, description="Raw API response data"
    )

    @field_validator("postcode")
    def validate_postcode(cls, v):
        """Validate and format UK postcode if provided"""
        if v:
            # Remove spaces and convert to uppercase
            v = v.replace(" ", "").upper()
            # Format with space before the last 3 characters
            if len(v) > 3:
                v = v[:-3] + " " + v[-3:]
        return v


class AddressResolver:
    """Class to resolve addresses using Google's Geocoding API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"

    def get_address_from_coordinates(
        self, latitude: float, longitude: float
    ) -> UKAddress:
        """
        Get address details from latitude and longitude using Google's Reverse Geocoding API

        Args:
            latitude: The latitude coordinate
            longitude: The longitude coordinate

        Returns:
            UKAddress: Parsed address information
        """
        params = {
            "latlng": f"{latitude},{longitude}",
            "key": self.api_key,
            "result_type": "street_address|premise|subpremise",  # Focus on detailed address results
            "language": "en",
        }

        try:
            response = requests.get(self.geocode_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK":
                logger.warning(f"Geocoding API returned status: {data['status']}")
                if "error_message" in data:
                    logger.error(f"Error message: {data['error_message']}")

                # Return a partially filled address with the coordinates
                return UKAddress(
                    latitude=latitude, longitude=longitude, raw_response=data
                )

            # Process the response to extract address components
            return self._parse_geocode_response(
                data, latitude=latitude, longitude=longitude
            )

        except Exception as e:
            logger.error(f"Error getting address from coordinates: {e}")
            # Return a minimal address with the coordinates
            return UKAddress(latitude=latitude, longitude=longitude)

    def get_address_from_postcode(self, postcode: str) -> UKAddress:
        """
        Get address details from a UK postcode using Google's Geocoding API

        Args:
            postcode: UK postcode

        Returns:
            UKAddress: Parsed address information
        """
        # Format postcode for API request
        formatted_postcode = postcode.replace(" ", "").upper()
        if len(formatted_postcode) > 3:
            formatted_postcode = formatted_postcode[:-3] + " " + formatted_postcode[-3:]

        params = {
            "address": formatted_postcode + ", UK",
            "key": self.api_key,
            "language": "en",
        }

        try:
            response = requests.get(self.geocode_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK":
                logger.warning(f"Geocoding API returned status: {data['status']}")
                if "error_message" in data:
                    logger.error(f"Error message: {data['error_message']}")

                # Return a partially filled address with the postcode
                return UKAddress(
                    postcode=postcode, input_postcode=postcode, raw_response=data
                )

            # Extract coordinates from the first result
            location = data["results"][0]["geometry"]["location"]
            latitude = location["lat"]
            longitude = location["lng"]

            # Process the response to extract address components
            address = self._parse_geocode_response(
                data, latitude=latitude, longitude=longitude
            )
            address.input_postcode = postcode

            return address

        except Exception as e:
            logger.error(f"Error getting address from postcode: {e}")
            # Return a minimal address with the postcode
            return UKAddress(postcode=postcode, input_postcode=postcode)

    def _parse_geocode_response(
        self,
        data: Dict[str, Any],
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> UKAddress:
        """
        Parse the Google Geocoding API response into a UKAddress object

        Args:
            data: The raw API response data
            latitude: Optional latitude used for the request
            longitude: Optional longitude used for the request

        Returns:
            UKAddress: Parsed address information
        """
        if not data.get("results"):
            return UKAddress(latitude=latitude, longitude=longitude, raw_response=data)

        # Use the most detailed result (usually the first one)
        result = data["results"][0]
        components = result.get("address_components", [])

        # Initialize address fields
        house_number = None
        building_name = None
        street_name = None
        locality = None
        city = None
        county = None
        postcode = None
        country = "United Kingdom"

        # Extract address components
        for component in components:
            types = component.get("types", [])

            if "street_number" in types:
                house_number = component.get("long_name")

            elif "route" in types:
                street_name = component.get("long_name")

            elif "premise" in types or "subpremise" in types:
                # This could be a building name
                building_name = component.get("long_name")

            elif "neighborhood" in types or "sublocality" in types:
                locality = component.get("long_name")

            elif "postal_town" in types or "locality" in types:
                city = component.get("long_name")

            elif "administrative_area_level_2" in types:
                county = component.get("long_name")

            elif "postal_code" in types:
                postcode = component.get("long_name")

            elif "country" in types and component.get("long_name") != "United Kingdom":
                country = component.get("long_name")

        # Create and return the address object
        return UKAddress(
            house_number=house_number,
            building_name=building_name,
            street_name=street_name,
            locality=locality,
            city=city,
            county=county,
            postcode=postcode,
            country=country,
            latitude=latitude,
            longitude=longitude,
            raw_response=data,
        )


# %% Export address_resolver
address_resolver = AddressResolver(api_key=API_KEY)


""" # %%
# %% usage
# Example usage

# Create an instance of the AddressResolver
address_resolver = AddressResolver(api_key=API_KEY)
address_resolver
# %%    
    # Example 1: Get address from coordinates (London Eye)
london_eye_address = address_resolver.get_address_from_coordinates(51.261613837352556, -1.0888995194177036)
print("Address from coordinates:")
print(london_eye_address.model_dump_json(indent=2, exclude={"raw_response"}))
    
# %%
    # Example 2: Get address from postcode
postcode_address = address_resolver.get_address_from_postcode("ig27hr")  # Buckingham Palace
print("\nAddress from postcode:")
print(postcode_address.model_dump_json(indent=2, exclude={"raw_response"}))

type(postcode_address)
# %%
"""
