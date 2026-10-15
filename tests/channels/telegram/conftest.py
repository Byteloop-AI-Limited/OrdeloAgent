"""Offline helpers for Telegram adapter tests: a recording Bot API session and update builders."""

from __future__ import annotations

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import Message


class RecordingSession(BaseSession):
    """Captures outgoing Bot API calls and returns minimal valid results. No network."""

    def __init__(self):
        super().__init__()
        self.calls: list = []
        self.closed = False

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message.model_validate(
                {
                    "message_id": len(self.calls),
                    "date": 0,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "text": method.text,
                },
                context={"bot": bot},
            )
        return True

    async def close(self):
        self.closed = True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        if False:
            yield b""

    @property
    def sent_texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, SendMessage)]

    @property
    def edited_texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, EditMessageText)]

    @property
    def last_keyboard(self):
        sent = [c for c in self.calls if isinstance(c, SendMessage)]
        return sent[-1].reply_markup if sent else None


@pytest.fixture
def recording_bot():
    session = RecordingSession()
    return Bot(token="123456:TEST-token", session=session), session


def message_update(text: str, user_id: int = 111, update_id: int = 1, username: str = "ada") -> dict:
    is_cmd = text.startswith("/")
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10,
            "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Ada", "username": username},
            "text": text,
            **({"entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]} if is_cmd else {}),
        },
    }


def callback_update(data: str, user_id: int = 111, update_id: int = 2, username: str = "ada") -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "chat_instance": "ci",
            "data": data,
            "from": {"id": user_id, "is_bot": False, "first_name": "Ada", "username": username},
            "message": {
                "message_id": 10,
                "date": 1_700_000_000,
                "chat": {"id": user_id, "type": "private"},
                "text": "Link this chat?",
            },
        },
    }


class FakeResp:
    def __init__(self, data):
        self.data = data


class FakeInviteDb:
    """In-memory mimic of the three tgram_* SQL functions (same result vocabulary and rules)."""

    def __init__(self):
        self.invites: dict[str, dict] = {}
        self.restaurants = {"ELAS": "Ela's Kitchen", "WREN": "Wren <Cafe>"}
        self.rpc_names: list[str] = []

    def add(self, code="CODE12345678", rest_ref="ELAS", bot_key="rest_admin", status="pending"):
        self.invites[code] = dict(code=code, rest_ref=rest_ref, bot_key=bot_key, status=status, uid=None, cid=None,
                                  username=None, first_name=None)
        return code

    def _preview(self, a):
        r = self.invites.get(a["p_code"])
        if not r or r["bot_key"] != a["p_bot_key"]:
            return {"result": "unknown"}
        res = ("revoked" if r["status"] == "revoked"
               else "claimed_by_you" if r["status"] == "claimed" and r["uid"] == a["p_user_id"]
               else "used" if r["status"] == "claimed"
               else "expired" if r["status"] == "expired"
               else "pending")
        return {"result": res, "rest_ref": r["rest_ref"], "rest_name": self.restaurants[r["rest_ref"]]}

    def _claim(self, a):
        r = self.invites.get(a["p_code"])
        if r and r["bot_key"] == a["p_bot_key"] and r["status"] == "pending":
            if any(o["status"] == "claimed" and o["uid"] == a["p_user_id"] and o["rest_ref"] == r["rest_ref"]
                   for o in self.invites.values()):
                return {"result": "already_linked"}
            r.update(status="claimed", uid=a["p_user_id"], cid=a["p_chat_id"],
                     username=a["p_username"], first_name=a["p_first_name"])
            return {"result": "ok", "rest_ref": r["rest_ref"], "rest_name": self.restaurants[r["rest_ref"]]}
        return self._preview(a)

    def _linked(self, a):
        return [{"rest_ref": r["rest_ref"], "rest_name": self.restaurants[r["rest_ref"]]}
                for r in self.invites.values()
                if r["status"] == "claimed" and r["uid"] == a["p_user_id"] and r["bot_key"] == a["p_bot_key"]]

    def rpc(self, name, args=None):
        self.rpc_names.append(name)
        fn = {"t_invite_preview": self._preview, "t_claim_invite": self._claim,
              "t_linked_restaurants": self._linked}[name]
        data = fn(args or {})
        return type("Q", (), {"execute": lambda self_: FakeResp(data)})()


@pytest.fixture
def invite_db(monkeypatch):
    db = FakeInviteDb()
    monkeypatch.setattr("channels.telegram.invites.client_ordelo_service", db)
    return db
