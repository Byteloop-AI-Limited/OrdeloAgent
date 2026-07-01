"""Tests for ThreadHandler PostgreSQL function wrappers.

The fake async pool matches SQL fragments and records calls, giving coverage of
query selection, parameters, and return-shape handling without Postgres.

Key Functions:
  - test_create_thread_calls_function_with_agent_and_recipient
  - test_get_active_thread_returns_row
  - test_make_threads_inactive_returns_message
  - test_get_stale_active_threads_returns_rows
  - test_get_or_create_thread_returns_tuple_or_default
"""

from __future__ import annotations

from utils_common.thread_management.thread_handler import ThreadHandler


async def test_create_thread_calls_function_with_agent_and_recipient(fake_pool) -> None:
    fake_pool.register_sql("create_thread", [{"thread_id": "thread-1"}])
    handler = ThreadHandler(fake_pool, agent="TEST")

    result = await handler.create_thread("447400000000")

    assert result == {"thread_id": "thread-1"}
    assert fake_pool.all_executes[-1].params == ("TEST", "447400000000")


async def test_get_active_thread_returns_row(fake_pool) -> None:
    fake_pool.register_sql("get_active_thread", [{"thread_id": "thread-1"}])

    assert await ThreadHandler(fake_pool, agent="TEST").get_active_thread("4474") == {"thread_id": "thread-1"}


async def test_make_threads_inactive_returns_message(fake_pool) -> None:
    fake_pool.register_sql("make_threads_inactive", [(3,)])

    assert await ThreadHandler(fake_pool, agent="TEST").make_threads_inactive("4474") == {"message": "3 thread(s) marked as inactive."}


async def test_get_stale_active_threads_returns_rows(fake_pool) -> None:
    fake_pool.register_sql("get_stale_active_threads", [{"thread_id": "old"}])

    assert await ThreadHandler(fake_pool, agent="TEST").get_stale_active_threads(10) == [{"thread_id": "old"}]
    assert fake_pool.all_executes[-1].params == ("TEST", 10)


async def test_get_or_create_thread_returns_tuple_or_default(fake_pool) -> None:
    fake_pool.register_sql("get_or_create_thread", [{"thread_id": "thread-1", "was_created": True}])
    assert await ThreadHandler(fake_pool, agent="TEST").get_or_create_thread("4474") == ("thread-1", True)

    empty_pool = type(fake_pool)()
    empty_pool.register_sql("get_or_create_thread", [])
    assert await ThreadHandler(empty_pool, agent="TEST").get_or_create_thread("4474") == (None, False)
