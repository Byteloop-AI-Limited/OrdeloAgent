"""
Durable Telegram inbox (t_inbox): handle selected consequential updates at most once.
    . Thin async wrapper over two SQL functions (RPCs). "Is this the first time?" is decided in the
      database, so any of the (up to 3) gunicorn workers gives the same answer.
    . RPCs and table are DEFINED in: ordelo_datamodels/telegram/t_inbox.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        claim   -> t_inbox_claim(p_bot_key, p_update_id, p_kind, p_tuid)      'new' | 'duplicate'
        finish  -> t_inbox_finish(p_bot_key, p_update_id, p_status, p_error)  'ok' | 'not_processing'
    . Table behind them: t_inbox (primary key (bot_key, update_id))
    . Called by: protected restaurant and rider handlers through process_once below
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Policy: at-most-once for opted-in handlers. A duplicate is skipped, also when the first attempt failed or died.
      If the inbox itself is unavailable the update is handled anyway (fail OPEN). Order SQL remains
      atomic; an agent turn can run twice on a redelivery during an inbox outage.
    . This is deduplication, not a durable queue: the webhook answers 200 before processing.
      For background agent turns, done means queued, not completed.
    . Overview and cross-reference table: docs/telegram-layer.md
  Classes/Functions:
    . claim
    . finish
    . process_once

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . t_inbox_claim (function, ordelo_datamodels/telegram/t_inbox.sql): calls (name passed to a helper)
  . t_inbox_finish (function, ordelo_datamodels/telegram/t_inbox.sql): calls (name passed to a helper)
(end of database objects)
"""

import asyncio
from typing import Any, Awaitable, Callable

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


async def process_once(
    bot_key: str, event: Update, tuid: int | None, work: Callable[[], Awaitable[Any]]
) -> Any:
    """Claim a selected update, run its handler once across workers, and record its outcome.

    A failed claim runs the work anyway. A failed finish is logged without changing the handler result.
    A background agent turn is recorded done once queued; its later result is outside this guard.
    """
    try:
        fresh = await claim(bot_key, event.update_id, event.event_type, tuid)
    except Exception:  # inbox DB down: fail open
        logger.exception(f"telegram[{bot_key}]: inbox claim failed for update {event.update_id}; processing anyway")
        return await work()
    if not fresh:
        logger.info(f"telegram[{bot_key}]: duplicate update {event.update_id} skipped")
        return None
    try:
        result = await work()
    except BaseException as exc:  # includes CancelledError from the route's wait_for timeout
        await _finish_quietly(bot_key, event.update_id, "failed", repr(exc))
        raise
    await _finish_quietly(bot_key, event.update_id, "done")
    return result
