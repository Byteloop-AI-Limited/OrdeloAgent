# %%
from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field, model_validator
from enum import Enum
import re
from datetime import datetime, timezone, date
from uuid import uuid4
import base64

def short_uuid():
    return base64.urlsafe_b64encode(uuid4().bytes).rstrip(b'=').decode('ascii')

class Location(BaseModel):
    topic: str
    rider_id: str
    recipient: str
    order_number: str
    acc: Optional[int] = None
    alt: Optional[int] = None
    batt: Optional[int] = None
    lat: float
    lon: float
    t: Optional[Literal["p", "c", "C", "b", "r", "u", "t", "v"]] = None
    tst: int
    tid: str
    conn: Optional[Literal["w", "o", "m"]] = None
    inregions: Optional[List[str]] = None
    inrids: Optional[List[str]] = None
    SSID: Optional[str] = None
    created_at: Optional[int] = None
    m: Optional[int] = None
    dt: Optional[date] = None
    dtts: Optional[datetime] = None
    id: str = Field(default_factory=short_uuid)

    @model_validator(mode="before")
    def set_topic_fields(cls, values):
        topic = values.get('topic', '')
        match = re.match(r"owntracks/(?P<rider_id>[^/]+)/(?P<recipient>[^-]+)-(?P<order_number>.+)$", topic)
        if match:
            values['rider_id'] = match.group('rider_id')
            values['recipient'] = match.group('recipient')
            values['order_number'] = match.group('order_number')
        tst = values.get('tst')
        if tst is not None:
            dt_obj = datetime.fromtimestamp(tst, tz=timezone.utc)
            values['dt'] = dt_obj.date()
            values['dtts'] = dt_obj
        return values