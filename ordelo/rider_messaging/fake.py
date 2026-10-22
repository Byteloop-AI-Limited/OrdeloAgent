"""A recording RiderMessenger for tests: no network, every call kept in .calls as (method, kwargs).

Use it wherever a test needs to see WHAT was said to a rider without caring about the channel:
    fake = RecordingRiderMessenger()
    with use_messenger(fake): ...           # ordelo.rider_messaging.factory.use_messenger
    assert fake.texts == ["Heads up ..."]
"""

from __future__ import annotations

from itertools import count
from typing import Any

from .models import MsgRef


class RecordingRiderMessenger:
    def __init__(self, channel: str = "whatsapp", rider_id: str | None = None):
        self.channel = channel
        self.rider_id = rider_id
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._ids = count(1)

    def _record(self, method: str, **kwargs) -> MsgRef:
        self.calls.append((method, kwargs))
        return MsgRef(f"fake:{next(self._ids)}")

    async def say(self, text, *, reply_to=None, header=None, footer=None, link=None) -> MsgRef:
        return self._record("say", text=text, reply_to=reply_to, header=header, footer=footer, link=link)

    async def send_place(self, place, *, reply_to=None) -> MsgRef:
        return self._record("send_place", place=place, reply_to=reply_to)

    async def request_location(self, prompt) -> MsgRef:
        return self._record("request_location", prompt=prompt)

    async def send_contact(self, contact) -> MsgRef:
        return self._record("send_contact", contact=contact)

    async def mark(self, ref, ok) -> None:
        self._record("mark", ref=ref, ok=ok)

    async def offer_job(self, offer) -> MsgRef:
        return self._record("offer_job", offer=offer)

    async def offer_closed(self, ref, order_number, reason) -> None:
        self._record("offer_closed", ref=ref, order_number=order_number, reason=reason)

    @property
    def texts(self) -> list[str]:
        return [kw["text"] for m, kw in self.calls if m == "say"]

    @property
    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]
