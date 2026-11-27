"""Service-role RPCs defined in ordelo_datamodels/telegram/t_rider_invites.sql (table: telegram/t_invites.sql).

issue, revoke, claim, take_alert and finish_alert map to the corresponding
t_rider_invite_* functions. The bearer is returned only by issue(). Transport
errors must never be formatted with the request or its arguments.

Database objects (definitions under ordelo_datamodels/):
  . t_rider_invite_issue (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
  . t_rider_invite_revoke (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
  . t_rider_invite_claim (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
  . t_rider_invite_alert_take (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
  . t_rider_invite_alert_finish (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
(end of database objects)
"""

import asyncio
import re
from dataclasses import dataclass
from uuid import UUID

_CODE = re.compile(r"ri_[A-Za-z0-9_-]{32}")
_START = re.compile(r"/start(?:@[A-Za-z0-9_]+)?\s+(ri_[A-Za-z0-9_-]{32})", re.IGNORECASE)
_PHONE = re.compile(r"\+?[1-9][0-9 ().-]*")


def is_invite_code(code: str | None) -> bool:
    return bool(code and _CODE.fullmatch(code))


def is_invite_start(text: str | None) -> bool:
    """Classify possible rider invite updates before the webhook acknowledges them."""
    match = _START.fullmatch((text or "").strip())
    return bool(match and is_invite_code(match[1]))


def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    digits = re.sub(r"[^0-9]", "", phone)
    if not _PHONE.fullmatch(phone) or not 8 <= len(digits) <= 12:
        raise ValueError("Supply one international phone number with 8–12 digits.")
    return digits


@dataclass(frozen=True)
class RiderInviteClaim:
    result: str  # ok | replay | unavailable | tuid_taken


@dataclass(frozen=True)
class RiderInviteAlert:
    update_id: int
    phone_tail: str
    tuid: int
    username: str | None
    previous_tuid: int | None
    previous_username: str | None
    accepted: list[str]


async def _rpc(name: str, args: dict) -> dict:
    from config import client_ordelo_service

    data = (await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())).data
    if not isinstance(data, dict) or not isinstance(data.get("result"), str):
        raise RuntimeError(f"Unexpected {name} result")
    return data


async def issue(phone: str) -> str:
    out = await _rpc("t_rider_invite_issue", {"p_phone": normalize_phone(phone)})
    code = out.get("code")
    if out["result"] != "ok" or not isinstance(code, str) or not is_invite_code(code):
        raise RuntimeError("Rider invite issuance failed")
    return f"https://t.me/ByteloopRidersBot?start={code}"


async def revoke(phone: str) -> str:
    out = await _rpc("t_rider_invite_revoke", {"p_phone": normalize_phone(phone)})
    return out["result"]


async def claim(
    code: str, update_id: int, tuid: int, tcid: int, username: str | None, first_name: str | None
) -> RiderInviteClaim:
    out = await _rpc("t_rider_invite_claim", {
        "p_code": code, "p_update_id": update_id, "p_tuid": tuid, "p_tcid": tcid,
        "p_username": username, "p_first_name": first_name,
    })
    if out["result"] not in {"ok", "replay", "unavailable", "tuid_taken"}:
        raise RuntimeError("Unexpected rider invite claim result")
    return RiderInviteClaim(out["result"])


async def take_alert(lease: UUID) -> RiderInviteAlert | None:
    out = await _rpc("t_rider_invite_alert_take", {"p_lease": str(lease)})
    if out.pop("result") == "empty":
        return None
    return RiderInviteAlert(**out)


async def finish_alert(update_id: int, lease: UUID, result: str, accepted: list[str]) -> str:
    out = await _rpc("t_rider_invite_alert_finish", {
        "p_update_id": update_id, "p_lease": str(lease), "p_result": result, "p_accepted": accepted,
    })
    return out["result"]
