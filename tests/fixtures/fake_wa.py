"""In-memory fakes for the pywa(_async) WhatsApp clients used in OrdeloAgent.

Production code calls ``_async_wa_client.send_message(...)``,
``send_template(...)``, ``send_interactive_message(...)`` etc. These fakes
record every call so tests can assert the right recipient/text/template was
dispatched without contacting WhatsApp.

Key Functions:
  - SentMessage - dataclass capturing one outbound call
  - FakeAsyncWhatsApp - async client recording all sends
  - FakeSyncWhatsApp - sync client recording all sends
  - FakeSendResult - send return value with dict-style and attribute id access
  - FakeMessage / FakeCallbackButton - inbound message/callback builders with reply recording
  - fake_async_wa - pytest fixture
  - patch_async_wa_client - pytest fixture replacing config._async_wa_client
"""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass
class SentMessage:
    """One recorded outbound WhatsApp call."""

    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeSendResult:
    """Shape-compatible enough for call sites expecting ``result.id`` or ``result["id"]``."""

    id: str

    def __getitem__(self, key: str) -> str:
        if key != "id":
            raise KeyError(key)
        return self.id


class _FakeWhatsAppBase:
    def __init__(self) -> None:
        self.sent: list[SentMessage] = []

    def _record(self, method: str, **kwargs: Any) -> FakeSendResult:
        self.sent.append(SentMessage(method=method, kwargs=kwargs))
        return FakeSendResult(id=f"wamid.{method}.{len(self.sent)}")


class FakeAsyncWhatsApp(_FakeWhatsAppBase):
    """Async pywa client stand-in. All ``send_*`` are async no-ops that record."""

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_message", **kwargs)

    async def send_template(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_template", **kwargs)

    async def send_interactive_message(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_interactive_message", **kwargs)

    async def send_location(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_location", **kwargs)

    async def request_location(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("request_location", **kwargs)

    async def send_contact(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_contact", **kwargs)

    async def send_image(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_image", **kwargs)

    async def send_document(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_document", **kwargs)

    async def send_catalog(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_catalog", **kwargs)

    async def upload_media(self, **kwargs: Any) -> str:
        self._record("upload_media", **kwargs)
        return "fake-media-id"

    def __getattr__(self, item: str):
        # Fallback: any other method recorded as async no-op.
        async def _async_recorder(**kwargs: Any) -> dict[str, Any]:
            return self._record(item, **kwargs)

        return _async_recorder


class FakeSyncWhatsApp(_FakeWhatsAppBase):
    """Sync pywa client stand-in. Same surface as the async one but blocking."""

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_message", **kwargs)

    def send_template(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("send_template", **kwargs)

    def get_business_phone_number(self, *_a: Any, **_kw: Any):
        m = MagicMock(name="FakeBusinessPhone")
        m.verified_name = "Byteloop Ai"
        m.webhook_configuration = {"whatsapp_business_account": "https://test/"}
        return m

    def __getattr__(self, item: str):
        def _recorder(**kwargs: Any) -> dict[str, Any]:
            return self._record(item, **kwargs)

        return _recorder


# ---------------------------------------------------------------------------
# Inbound message / callback builders
# ---------------------------------------------------------------------------


class FakeMessage:
    """Minimal stand-in for ``pywa.types.Message`` used by handlers."""

    def __init__(
        self,
        sender: str = "447400000000",
        text: str = "",
        data: str | None = None,
        timestamp: int | None = None,
    ) -> None:
        self.sender = sender
        self.text = text
        self.data = data
        self.timestamp = timestamp
        # Some handlers read msg.from_user.wa_id
        self.from_user = MagicMock(wa_id=sender)
        self.body = text
        self.id = f"wamid.inbound.{sender}"
        self.replies: list[dict[str, Any]] = []

    async def indicate_typing(self) -> None:
        return None

    async def reply_text(self, text: str, **_: Any) -> None:
        self.replies.append({"text": text, **_})
        return None

    async def reply(self, text: str, **_: Any) -> None:
        self.replies.append({"text": text, **_})
        return None


class FakeCallbackButton:
    """Stand-in for ``pywa.types.CallbackButton``."""

    def __init__(self, data: str = "{}") -> None:
        self.data = data


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_async_wa() -> FakeAsyncWhatsApp:
    return FakeAsyncWhatsApp()


@pytest.fixture
def fake_sync_wa() -> FakeSyncWhatsApp:
    return FakeSyncWhatsApp()


@pytest.fixture
def patch_async_wa_client(monkeypatch, fake_async_wa) -> FakeAsyncWhatsApp:
    """Replace module-level async WA client across all import sites."""
    import config
    from config import waba_setting

    monkeypatch.setattr(waba_setting, "_async_wa_client", fake_async_wa, raising=True)
    monkeypatch.setattr(config, "_async_wa_client", fake_async_wa, raising=False)
    for module in list(sys.modules.values()):
        if module is None:
            continue
        if hasattr(module, "_async_wa_client"):
            monkeypatch.setattr(module, "_async_wa_client", fake_async_wa, raising=False)
    return fake_async_wa


@pytest.fixture
def patch_sync_wa_client(monkeypatch, fake_sync_wa) -> FakeSyncWhatsApp:
    import config
    from config import waba_setting

    monkeypatch.setattr(waba_setting, "_sync_wa_client", fake_sync_wa, raising=True)
    monkeypatch.setattr(config, "_sync_wa_client", fake_sync_wa, raising=False)
    return fake_sync_wa
