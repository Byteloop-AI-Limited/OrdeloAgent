"""Scripted fake ``ChatOpenAI`` substitute for LLM-driven code paths.

Production code uses ``llm_settings.llm_client`` (a ``langchain_openai.ChatOpenAI``
instance) for both bare ``invoke``/``ainvoke`` calls and graph-bound
``bind_tools(...)`` patterns.

Tests script the response queue and assert which prompt the LLM saw.

Key Functions:
  - FakeChatModel - returns scripted responses, records every invocation
  - fake_llm - pytest fixture
  - patch_llm_client - pytest fixture wiring fake into llm_settings
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

try:
    from langchain_core.messages import AIMessage  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - langchain not installed
    AIMessage = None  # type: ignore[assignment]


class FakeChatModel:
    """Returns scripted responses one per (a)invoke call."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._queue: deque[Any] = deque(responses or [])
        self.calls: list[Any] = []
        self.bound_tools: list[Any] | None = None

    def queue(self, *responses: Any) -> "FakeChatModel":
        self._queue.extend(responses)
        return self

    def _next(self) -> Any:
        if self._queue:
            return self._queue.popleft()
        if AIMessage is not None:
            return AIMessage(content="")
        return type("FakeAIMessage", (), {"content": "", "tool_calls": []})()

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self._next()

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        return self.invoke(messages, **kwargs)

    def bind_tools(self, tools: list[Any], **_: Any) -> "FakeChatModel":
        self.bound_tools = list(tools)
        return self

    def with_structured_output(self, schema: Any, **_: Any) -> "FakeChatModel":
        # Production sometimes uses .with_structured_output(...).invoke()
        return self


@pytest.fixture
def fake_llm() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def patch_llm_client(monkeypatch, fake_llm) -> FakeChatModel:
    """Wire ``fake_llm`` in so ``llm_settings.llm_client`` returns it."""
    from config import llm_setting

    monkeypatch.setattr(
        llm_setting.LLMSettings,
        "llm_client",
        property(lambda self: fake_llm),
        raising=True,
    )
    return fake_llm
