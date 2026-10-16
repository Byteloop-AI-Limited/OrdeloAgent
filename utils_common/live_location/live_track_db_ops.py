# %%
"""
Supabase helper class for persisting and querying live location data.
    . Dependencies: supabase-py, os, datetime
    . `LiveTrackHandler` wraps CRUD for `live-track` table
        - `_extract_user_device` parses OwnTracks topic to user & device id
        - `insert_location` maps payload dict to table schema and inserts row
        - `get_latest_location` fetches most recent record for a user/device
        - `get_user_locations` returns history with optional filters

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . live-track (table, ordelo_datamodels/rider_location/live_track.sql): named in code (passed to a query helper)
(end of database objects)
"""

# NOTE: legacy summary moved to module docstring above
from typing import Dict, List, Optional
import os
from supabase import create_client, Client
from config import pg_settings

pg_settings


# %%
class LiveTrackHandler:
    def __init__(self):
        # Initialize Supabase client
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase credentials not found in environment variables")
        self.supabase: Client = create_client(supabase_url, supabase_key)
        self.table_name = "live-track"

    def _extract_user_device(self, topic: str) -> tuple[str, str]:
        """Extract user and device_id from topic string"""
        try:
            parts = topic.split("/")
            if len(parts) != 3:
                raise ValueError(f"Invalid topic format: {topic}")
            return parts[1], parts[2]  # user, device_id
        except Exception as e:
            raise ValueError(f"Failed to parse topic: {topic}. Error: {str(e)}")

    async def insert_location(self, data: Dict) -> Dict:
        """
        Insert a new location record into Supabase
        Required fields: batt, created_at, lat, lon, topic, t, conn
        """
        try:
            user, device_id = self._extract_user_device(data["topic"])

            record = {
                "battery": data["batt"],
                "created_at": data["created_at"],
                "latitude": data["lat"],
                "longitude": data["lon"],
                "topic": data["topic"],
                "create_ts": data["readable_time"],
                "user_id": user,
                "device_id": device_id,
                "type": data["t"],
                "connection": data["conn"],
            }

            response = (
                await self.supabase.table(self.table_name).insert(record).execute()
            )
            return response.data[0]
        except Exception as e:
            raise Exception(f"Failed to insert location: {str(e)}")

    async def get_latest_location(
        self, user: str, device_id: Optional[str] = None
    ) -> Dict:
        """Get the latest location for a user and optionally specific device"""
        try:
            query = (
                self.supabase.table(self.table_name)
                .select("*")
                .eq("user_id", user)
                .order("created_at", desc=True)
                .limit(1)
            )

            if device_id:
                query = query.eq("device_id", device_id)

            response = await query.execute()
            return response.data[0] if response.data else None
        except Exception as e:
            raise Exception(f"Failed to get latest location: {str(e)}")

    async def get_user_locations(
        self,
        user: str,
        device_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict]:
        """Get location history for a user with optional filters"""
        try:
            query = (
                self.supabase.table(self.table_name)
                .select("*")
                .eq("user_id", user)
                .order("created_at", desc=True)
            )

            if device_id:
                query = query.eq("device_id", device_id)
            if start_time:
                query = query.gte("created_at", start_time)
            if end_time:
                query = query.lte("created_at", end_time)

            response = await query.execute()
            return response.data
        except Exception as e:
            raise Exception(f"Failed to get user locations: {str(e)}")
