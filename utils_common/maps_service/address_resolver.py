# %%
"""
Resolve addresses and calculate driving routes using Google Maps APIs
    . Uses Google Maps Geocoding API to convert addresses into geocode data
    . Uses Google Maps Directions API to calculate driving routes and distances
    . Defines Pydantic models for API response components
    . Provides functions to fetch geocode results and extract formatted addresses
    . Provides functions to calculate driving distances between postcodes/coordinates
  Classes:
    . AddressComponent - Model for address components
    . GeocodeResult - Model for geocode result
    . GeocodeResponse - Model for geocode response
    . UKAddress - Model for UK address
    . AddressResolver - Resolve addresses using Google Geocoding API
    . RouteStep - Model for a single step in a route
    . RouteLeg - Model for a leg of a route
    . Route - Model for a single route from Directions API
    . DirectionsResponse - Model for Directions API response
    . DrivingRoute - Model for processed driving route result
    . DrivingDistanceCalculator - Calculate driving distances using Directions API
"""

# %%
import logging
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, Field, field_validator

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


class RouteStep(BaseModel):
    """Model for a single step in a route"""

    distance: Dict[str, Any] = Field(
        ..., description="Distance information for this step"
    )
    duration: Dict[str, Any] = Field(
        ..., description="Duration information for this step"
    )
    html_instructions: str = Field(..., description="HTML formatted instructions")
    travel_mode: str = Field(..., description="Travel mode for this step")


class RouteLeg(BaseModel):
    """Model for a leg of a route"""

    distance: Dict[str, Any] = Field(..., description="Total distance for this leg")
    duration: Dict[str, Any] = Field(..., description="Total duration for this leg")
    start_address: str = Field(..., description="Starting address")
    end_address: str = Field(..., description="Ending address")
    start_location: Dict[str, float] = Field(..., description="Starting coordinates")
    end_location: Dict[str, float] = Field(..., description="Ending coordinates")
    steps: List[RouteStep] = Field(
        default_factory=list, description="Steps in this leg"
    )


class Route(BaseModel):
    """Model for a single route from Directions API"""

    summary: str = Field(..., description="Summary description of the route")
    legs: List[RouteLeg] = Field(..., description="Legs of the route")
    overview_polyline: Dict[str, str] = Field(
        ..., description="Encoded polyline for the route"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Warnings for this route"
    )
    waypoint_order: List[int] = Field(
        default_factory=list, description="Order of waypoints"
    )


class DirectionsResponse(BaseModel):
    """Model for the full response from Google Directions API"""

    routes: List[Route] = Field(default_factory=list, description="Available routes")
    status: str = Field(..., description="Status of the request")
    error_message: Optional[str] = Field(
        None, description="Error message if status is not OK"
    )


class DrivingRoute(BaseModel):
    """Model for processed driving route result"""

    origin_address: str = Field(..., description="Origin address")
    destination_address: str = Field(..., description="Destination address")
    distance_text: Optional[str] = Field(None, description="Human-readable distance")
    distance_meters: Optional[int] = Field(None, description="Distance in meters")
    distance_miles: Optional[float] = Field(None, description="Distance in miles")
    duration_text: Optional[str] = Field(None, description="Human-readable duration")
    duration_seconds: Optional[int] = Field(None, description="Duration in seconds")
    summary: Optional[str] = Field(None, description="Route summary")
    warnings: List[str] = Field(
        default_factory=list,
        description="Warnings for this route (e.g., tolls, road closures)",
    )
    status: str = Field(..., description="Status of the calculation")
    raw_route: Optional[Dict[str, Any]] = Field(
        None, description="Raw route data from API"
    )


class DrivingDistanceCalculator:
    """Class to calculate driving distances and routes using Google's Directions API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.directions_url = "https://maps.googleapis.com/maps/api/directions/json"
        self.address_resolver = AddressResolver(api_key)

    def calculate_route_between_postcodes(
        self, origin_postcode: str, destination_postcode: str, alternatives: bool = True
    ) -> list[DrivingRoute]:
        """
        Calculate driving routes between two UK postcodes using Directions API

        Args:
            origin_postcode: Origin UK postcode
            destination_postcode: Destination UK postcode
            alternatives: Whether to request alternative routes (default: True)

        Returns:
            List[DrivingRoute]: List of available routes with distance and duration information
        """
        # Get coordinates for postcodes
        origin_address = self.address_resolver.get_address_from_postcode(
            origin_postcode
        )
        destination_address = self.address_resolver.get_address_from_postcode(
            destination_postcode
        )

        if not origin_address.latitude or not origin_address.longitude:
            logger.error(f"Could not resolve origin postcode: {origin_postcode}")
            return [
                DrivingRoute(
                    origin_address=origin_postcode,
                    destination_address=destination_postcode,
                    status="ORIGIN_NOT_FOUND",
                )
            ]

        if not destination_address.latitude or not destination_address.longitude:
            logger.error(
                f"Could not resolve destination postcode: {destination_postcode}"
            )
            return [
                DrivingRoute(
                    origin_address=origin_postcode,
                    destination_address=destination_postcode,
                    status="DESTINATION_NOT_FOUND",
                )
            ]

        return self.calculate_route_between_coordinates(
            origin_lat=origin_address.latitude,
            origin_lng=origin_address.longitude,
            destination_lat=destination_address.latitude,
            destination_lng=destination_address.longitude,
            alternatives=alternatives,
        )

    def calculate_route_between_coordinates(
        self,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        alternatives: bool = True,
    ) -> List[DrivingRoute]:
        """
        Calculate driving routes between two coordinate pairs using Directions API

        Args:
            origin_lat: Origin latitude
            origin_lng: Origin longitude
            destination_lat: Destination latitude
            destination_lng: Destination longitude
            alternatives: Whether to request alternative routes (default: True)

        Returns:
            List[DrivingRoute]: List of available routes with distance and duration information
        """
        origin = f"{origin_lat},{origin_lng}"
        destination = f"{destination_lat},{destination_lng}"

        params = {
            "origin": origin,
            "destination": destination,
            "mode": "driving",
            "alternatives": str(alternatives).lower(),
            "key": self.api_key,
            "language": "en",
            "units": "imperial",
        }

        try:
            response = requests.get(self.directions_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data["status"] != "OK":
                logger.warning(f"Directions API returned status: {data['status']}")
                if "error_message" in data:
                    logger.error(f"Error message: {data['error_message']}")

                return [
                    DrivingRoute(
                        origin_address=origin,
                        destination_address=destination,
                        status=data["status"],
                        raw_route=data,
                    )
                ]

            # Parse all available routes
            routes = []
            for route in data.get("routes", []):
                if not route.get("legs"):
                    continue

                # Get the first leg (for single origin-destination, there's only one leg)
                leg = route["legs"][0]

                # Extract distance and duration
                distance_info = leg.get("distance", {})
                duration_info = leg.get("duration", {})

                # Convert meters to miles
                distance_meters = distance_info.get("value")
                distance_miles = None
                if distance_meters:
                    distance_miles = round(distance_meters * 0.000621371, 2)

                driving_route = DrivingRoute(
                    origin_address=leg.get("start_address", origin),
                    destination_address=leg.get("end_address", destination),
                    distance_text=distance_info.get("text"),
                    distance_meters=distance_meters,
                    distance_miles=distance_miles,
                    duration_text=duration_info.get("text"),
                    duration_seconds=duration_info.get("value"),
                    summary=route.get("summary"),
                    warnings=route.get("warnings", []),
                    status="OK",
                    raw_route=route,
                )
                routes.append(driving_route)

            if routes:
                routes.sort(key=lambda r: (r.duration_seconds or float("inf")))

            return (
                routes
                if routes
                else [
                    DrivingRoute(
                        origin_address=origin,
                        destination_address=destination,
                        status="NO_ROUTES_FOUND",
                        raw_route=data,
                    )
                ]
            )

        except Exception as e:
            logger.error(f"Error calculating route: {e}")
            return [
                DrivingRoute(
                    origin_address=origin,
                    destination_address=destination,
                    status="ERROR",
                    raw_route={"error": str(e)},
                )
            ]


# %% Export instances
address_resolver = AddressResolver(api_key=API_KEY)
driving_distance_calculator = DrivingDistanceCalculator(api_key=API_KEY)


# %%

""" # %% TEST
# %% usage
# Example usage

# Create an instance of the AddressResolver
address_resolver = AddressResolver(api_key=API_KEY)
address_resolver

# %%
# Example: Calculate straight-line distance between postcodes
address = address_resolver.get_address_from_postcode("SW1A 1AA")
address.latitude, address.longitude

# %%
# Example 1: Get address from coordinates (London Eye)
london_eye_address = address_resolver.get_address_from_coordinates(
    51.51163582887858, -0.13544498014148215
)
print("Address from coordinates:")
print(london_eye_address.model_dump_json(indent=2, exclude={"raw_response"}))

type(london_eye_address)

# %%
# Example 2: Get address from postcode
postcode_address = address_resolver.get_address_from_postcode("br66dn")  # Buckingham Palace
print("\nAddress from postcode:")
print(postcode_address.model_dump_json(indent=2, exclude={"raw_response"}))

type(postcode_address)

# %%
# Example 3: Calculate driving routes between postcodes with alternatives
routes = driving_distance_calculator.calculate_route_between_postcodes(
    "SW1X 7LY", "br66dn", alternatives=True
)
print("\nDriving routes between postcodes:")
for i, route in enumerate(routes, 1):
    print(f"\nRoute {i}:")
    print(f"  From: {route.origin_address}")
    print(f"  To: {route.destination_address}")
    print(f"  Distance: {route.distance_text} ({route.distance_miles} miles)")
    print(f"  Duration: {route.duration_text}")
    print(f"  Summary: {route.summary}")
    print(f"  Warnings: {route.warnings}")
    print(f"  Status: {route.status}")

# %%
# Example 4: Calculate driving routes between coordinates
routes_coords = driving_distance_calculator.calculate_route_between_coordinates(
    51.2625171747331,
    -1.08459464266133,  # Origin
    51.3540813695372,
    0.0959000805415555,  # Destination
    alternatives=True,
)
print("\nDriving routes between coordinates:")
for i, route in enumerate(routes_coords, 1):
    print(f"\nRoute {i}:")
    print(f"  Distance: {route.distance_text} ({route.distance_miles} miles)")
    print(f"  Duration: {route.duration_text}")
    print(f"  Summary: {route.summary}")
    print(f"  Warnings: {route.warnings}")
# %%
"""
