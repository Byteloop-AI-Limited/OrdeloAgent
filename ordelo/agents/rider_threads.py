"""
Rider threads: one LangGraph thread per assigned dispatch (D46, D47; ADR 0012 Amendment 1).
    . Deep module: callers ask "the thread of this dispatch", "this rider's open thread", "open / close it". They never
      build thread ids, query the shared thread table, or decide which thread a message belongs to.
    . thread_id = '<agent>-dispatch-<dispatch_id>' (agent = project_settings.rest_ref, 'ORDELO' on live). Built in SQL only
      (rider_thread_id); recorded on delivery_dispatch.thread_id, so lookups join and nothing parses the id.
    . A closed thread is never run and never re-created (no more get_or_create_thread for riders). Every run touches the
      thread first (last_access_dtts), which keeps the stale-thread close job honest.
    . At most one open rider thread per rider: opening a dispatch thread closes the others (cancellation aftercare included).
    . Threads opened before R2 ('ORDELO-<uuid>') are still found by active_for_rider (dispatch_id None, channel 'whatsapp')
      and closed by exact id.
    . RPCs are DEFINED in: ordelo_datamodels/agent_threads/rider_threads.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> SQL function it calls:
        open_for_dispatch -> rider_thread_open(p_agent, p_rider_id, p_dispatch_id)    opened | existing | closed | not_found
        touch             -> rider_thread_touch(p_thread_id)                        active | inactive | not_found
        active_for_rider  -> rider_thread_active(p_agent, p_rider_id, p_touch)      active | none
        describe          -> rider_thread_describe(p_thread_id, NULL)               found | not_found (read-only)
        for_dispatch      -> rider_thread_describe(NULL, p_dispatch_id)             found | not_found (read-only)
        close             -> rider_thread_close(p_thread_id)                        closed | not_active
    . Called by: ordelo/agents/agent_runner.py, ordelo/agents/rider_agent.py (close), watomation/routers/delivery_hooks.py
      (close_threads), watomation/on_message_wa_handler.py, watomation/on_wa_location_handler.py, ordelo/wa_location.py,
      channels/telegram/rider/jobs.py
    . Uses the psycopg pool (as ThreadHandler does): the functions are not exposed to anon / authenticated
  Classes/Functions:
    . RiderThread, OpenOutcome
    . open_for_dispatch, touch, active_for_rider, describe, for_dispatch, close

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_thread_open (function, ordelo_datamodels/agent_threads/rider_threads.sql): calls (SQL)
  . rider_thread_touch (function, ordelo_datamodels/agent_threads/rider_threads.sql): calls (SQL)
  . rider_thread_active (function, ordelo_datamodels/agent_threads/rider_threads.sql): calls (SQL)
  . rider_thread_describe (function, ordelo_datamodels/agent_threads/rider_threads.sql): calls (SQL)
  . rider_thread_close (function, ordelo_datamodels/agent_threads/rider_threads.sql): calls (SQL)
(end of database objects)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import pg_settings, project_settings


@dataclass(frozen=True)
class RiderThread:
    """A rider agent thread and what it belongs to. dispatch fields are None for a thread opened before R2."""

    thread_id: str
    rider_id: str
    is_active: bool = True
    dispatch_id: int | None = None
    order_number: str | None = None
    dispatch_status: str | None = None
    channel: str = "whatsapp"
    tcid: int | None = None

    @property
    def is_dispatch_thread(self) -> bool:
        return self.dispatch_id is not None


@dataclass(frozen=True)
class OpenOutcome:
    result: str  # opened | existing | closed | not_found
    thread_id: str
    closed: list[str] = field(default_factory=list)

    @property
    def is_new(self) -> bool:
        return self.result == "opened"


def _agent() -> str:
    return project_settings.rest_ref


async def _call(sql: str, params: tuple) -> Any:
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
    data = row[0] if row else None
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected rider thread response: {data!r}")
    return data


def _thread(data: dict) -> RiderThread | None:
    if data.get("thread_id") is None or data.get("result") in ("not_found", "none"):
        return None
    return RiderThread(
        thread_id=data["thread_id"],
        rider_id=data.get("rider_id") or "",
        is_active=bool(data.get("is_active", data.get("result") == "active")),
        dispatch_id=data.get("dispatch_id"),
        order_number=data.get("order_number"),
        dispatch_status=data.get("dispatch_status"),
        channel=data.get("channel") or "whatsapp",
        tcid=data.get("tcid"),
    )


async def open_for_dispatch(rider_id: str, dispatch_id: int) -> OpenOutcome:
    """Open the thread of an assigned dispatch. 'opened' only the first time: callers initialise the graph only then."""
    data = await _call("SELECT public.rider_thread_open(%s, %s, %s)", (_agent(), rider_id, dispatch_id))
    return OpenOutcome(data["result"], data.get("thread_id") or "", list(data.get("closed") or []))


async def touch(thread_id: str) -> RiderThread | None:
    """The thread, freshly touched, if it is OPEN; None when it is closed or unknown (never run a closed thread)."""
    data = await _call("SELECT public.rider_thread_touch(%s)", (thread_id,))
    return _thread(data) if data["result"] == "active" else None


async def active_for_rider(rider_id: str, *, touch: bool = True) -> RiderThread | None:
    """The rider's open rider thread (there is at most one), or None. touch=False for debug reads."""
    data = await _call("SELECT public.rider_thread_active(%s, %s, %s)", (_agent(), rider_id, touch))
    return _thread(data) if data["result"] == "active" else None


async def describe(thread_id: str) -> RiderThread | None:
    """Read-only snapshot by thread id (open or closed), or None."""
    return _thread(await _call("SELECT public.rider_thread_describe(%s, NULL)", (thread_id,)))


async def for_dispatch(dispatch_id: int) -> RiderThread | None:
    """Read-only snapshot of the dispatch's recorded thread (open or closed), or None (no thread opened yet)."""
    return _thread(await _call("SELECT public.rider_thread_describe(NULL, %s)", (dispatch_id,)))


async def close(thread_id: str) -> bool:
    """Close exactly this thread. True when it was open."""
    data = await _call("SELECT public.rider_thread_close(%s)", (thread_id,))
    return data["result"] == "closed"
