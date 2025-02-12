# %%
# https://maps.google.com/maps?saddr=51.354126,0.099301&daddr=51.364126,0.109301
# https://maps.googleapis.com/maps/api/directions/json?origin=51.354126,0.099301&destination=51.364126,0.109301&mode=driving&key=YOUR_API_KEY



# %%
import requests
import json


# Define origin and destination (latitude,longitude)
origin = "51.2625171747331,-1.08459464266133"
destination = "51.3540813695372,0.0959000805415555"

# Construct the URL.
# The parameter alternatives=true requests multiple routes if available.
url = (
    "https://maps.googleapis.com/maps/api/directions/json?"
    f"origin={origin}&destination={destination}&mode=driving&alternatives=true&key={API_KEY}"
)

# Send the request to the Directions API
response = requests.get(url)
data = response.json()

# Check if the response is OK
if data["status"] != "OK":
    print("Error:", data.get("error_message", data["status"]))
else:
    # Initialize variables to store the shortest distance and the corresponding route
    shortest_distance = float("inf")
    best_route = None

    # Iterate through each returned route
    for route in data["routes"]:
        # A route can have multiple legs, but for point-to-point directions there is typically one leg.
        for leg in route["legs"]:
            # distance value is in meters
            distance = leg["distance"]["value"]
            if distance < shortest_distance:
                shortest_distance = distance
                best_route = route

    # Convert meters to kilometers
    distance_km = shortest_distance / 1000.0
    distance_miles = shortest_distance * 0.000621371

    print(f"Shortest driving distance: {shortest_distance} meters ({distance_km:.2f} km) ({distance_miles:.2f} miles)")