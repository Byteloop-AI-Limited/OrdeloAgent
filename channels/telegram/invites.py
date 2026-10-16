"""
Telegram invite storage access (t_invites) for every Ordelo bot.
    . Thin async wrapper over the SQL functions (RPCs). The logic lives in the database, not here.
    . RPCs and tables are DEFINED in: ordelo_datamodels/telegram/t_invites.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        preview_invite    -> t_invite_preview(p_code, p_bot_key, p_user_id)    read-only classification
        claim_invite      -> t_claim_invite(p_code, p_bot_key, p_user_id, p_chat_id, p_username, p_first_name)
                             atomic claim (first valid caller wins), fills TID/TCID and username
        linked_restaurants-> t_linked_restaurants(p_bot_key, p_user_id)        restaurants this user is linked to
    . Table behind them: t_invites (also the t_invites_shareable view, used by operators, not by this module)
    . Called by: channels/telegram/rest_admin/router.py (cmd_start, on_invite_decision, cmd_whoami)
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Authorization stays with callers: a claimed invite only authenticates a person
    . Overview and cross-reference table: docs/telegram-layer.md
  Classes/Functions:
    . InviteOutcome
    . LinkedRestaurant
    . preview_invite
    . claim_invite
    . linked_restaurants

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . t_claim_invite (function, ordelo_datamodels/telegram/t_invites.sql): calls (name passed to a helper)
  . t_invite_preview (function, ordelo_datamodels/telegram/t_invites.sql): calls (name passed to a helper)
  . t_linked_restaurants (function, ordelo_datamodels/telegram/t_invites.sql): calls (name passed to a helper)
(end of database objects)
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from config import client_ordelo_service

# Telegram /start payloads allow A-Z a-z 0-9 _ - (max 64); t_new_invite_code() issues 12 of them.
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# preview results: unknown | revoked | expired | used | claimed_by_you | pending
# claim results:   ok | already_linked | (any preview result explaining why not)
CLAIMED_STATES = frozenset({"ok", "claimed_by_you"})


@dataclass(frozen=True)
class InviteOutcome:
    result: str
    rest_ref: str | None = None
    rest_name: str | None = None

    @property
    def is_linked(self) -> bool:
        return self.result in CLAIMED_STATES


@dataclass(frozen=True)
class LinkedRestaurant:
    rest_ref: str
    rest_name: str


def _outcome(data: Any) -> InviteOutcome:
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected tgram invite RPC response: {data!r}")
    return InviteOutcome(data["result"], data.get("rest_ref"), data.get("rest_name"))


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


async def preview_invite(bot_key: str, code: str, user_id: int) -> InviteOutcome:
    if not _CODE_RE.match(code or ""):
        return InviteOutcome("unknown")
    return _outcome(
        await _rpc("t_invite_preview", {"p_code": code, "p_bot_key": bot_key, "p_user_id": user_id})
    )


async def claim_invite(
    bot_key: str,
    code: str,
    *,
    user_id: int,
    chat_id: int,
    username: str | None,
    first_name: str | None,
) -> InviteOutcome:
    if not _CODE_RE.match(code or ""):
        return InviteOutcome("unknown")
    return _outcome(
        await _rpc(
            "t_claim_invite",
            {
                "p_code": code,
                "p_bot_key": bot_key,
                "p_user_id": user_id,
                "p_chat_id": chat_id,
                "p_username": username,
                "p_first_name": first_name,
            },
        )
    )


async def linked_restaurants(bot_key: str, user_id: int) -> list[LinkedRestaurant]:
    data = await _rpc("t_linked_restaurants", {"p_bot_key": bot_key, "p_user_id": user_id})
    return [LinkedRestaurant(r["rest_ref"], r["rest_name"]) for r in (data or [])]
