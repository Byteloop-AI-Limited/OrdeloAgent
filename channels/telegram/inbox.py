"""
Durable Telegram inbox (t_inbox): handle each Telegram update at most once.
    . Thin async wrapper over two SQL functions (RPCs). "Is this the first time?" is decided in the
      database, so any of the (up to 3) gunicorn workers gives the same answer.
    . RPCs and table are DEFINED in: ordelo_datamodels/migrations/create_t_inbox.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        claim   -> t_inbox_claim(p_bot_key, p_update_id, p_kind, p_tuid)      'new' | 'duplicate'
        finish  -> t_inbox_finish(p_bot_key, p_update_id, p_status, p_error)  'ok' | 'not_processing'
    . Table behind them: t_inbox (primary key (bot_key, update_id))
    . Called by: InboxMiddleware below, registered once per bot in channels/telegram/bots.py
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Policy: at-most-once. A duplicate is skipped, also when the first attempt failed or died.
      If the inbox itself is unavailable the update is handled anyway (fail OPEN): the state-changing
      SQL functions are atomic on their own, so a double delivery can not double-apply an order action.
    . The webhook route needs no change: it already answers 200 after the secret check.
    . Overview and cross-reference table: docs/telegram-layer.md
  Classes/Functions:
    . claim
    . finish
    . InboxMiddleware
"""

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update
from loguru import logger

from config import client_ordelo_service


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


def _result(data: Any, rpc_name: str) -> dict:
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected {rpc_name} RPC response: {data!r}")
    return data


async def claim(bot_key: str, update_id: int, kind: str, tuid: int | None) -> bool:
    """True if this call is the first for (bot_key, update_id) and the caller must handle the update."""
    data = _result(
        await _rpc(
            "t_inbox_claim",
            {"p_bot_key": bot_key, "p_update_id": update_id, "p_kind": kind, "p_tuid": tuid},
        ),
        "t_inbox_claim",
    )
    return data["result"] == "new"


async def finish(bot_key: str, update_id: int, status: str, error: str | None = None) -> str:
    """Close a 'processing' row as 'done' or 'failed'. Returns the RPC result ('ok' | 'not_processing')."""
    data = _result(
        await _rpc(
            "t_inbox_finish",
            {"p_bot_key": bot_key, "p_update_id": update_id, "p_status": status, "p_error": error},
        ),
        "t_inbox_finish",
    )
    return data["result"]


async def _finish_quietly(bot_key: str, update_id: int, status: str, error: str | None = None) -> None:
    try:
        await finish(bot_key, update_id, status, error)
    except Exception:
        logger.exception(f"telegram[{bot_key}]: inbox finish({status}) failed for update {update_id}")


class InboxMiddleware(BaseMiddleware):
    """Outer middleware on dp.update: claim (bot_key, update_id) before any handler; skip duplicates.

    aiogram's Dispatcher registers its user-context and error middlewares on dp.update first, so this
    one runs inside them: `event_from_user` is already set, and handler exceptions reach us before the
    error handlers in errors.py do.
    """

    def __init__(self, bot_key: str):
        self.bot_key = bot_key

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        try:
            fresh = await claim(self.bot_key, event.update_id, event.event_type, user.id if user else None)
        except Exception:  # inbox DB down: fail OPEN; state-changing RPCs are still atomic
            logger.exception(f"telegram[{self.bot_key}]: inbox claim failed for update {event.update_id}; processing anyway")
            return await handler(event, data)
        if not fresh:
            logger.info(f"telegram[{self.bot_key}]: duplicate update {event.update_id} skipped")
            return None
        try:
            result = await handler(event, data)
        except BaseException as exc:  # includes CancelledError from the route's wait_for timeout
            await _finish_quietly(self.bot_key, event.update_id, "failed", repr(exc))
            raise
        await _finish_quietly(self.bot_key, event.update_id, "done")
        return result
