"""In-memory fake of the Supabase REST client used across OrdeloAgent.

Production code uses ``pg_settings.client`` (a ``supabase.Client``) with the
builder-chain pattern:

    client.table("foo").select("*").eq("k", "v").execute()
    client.rpc("fn", {"arg": 1}).execute()
    client.schema("elas").table("foo").select("*").execute()

Tests register canned responses keyed by ``(table_or_rpc, verb, kwargs)`` and
inspect ``client.calls`` to assert the right SQL was issued.

Key Functions:
  - FakeSupabaseResponse - shape-compatible with Supabase APIResponse
  - FakeSupabaseQuery - records builder chain, returns scripted response
  - FakeSupabaseClient - top-level fake exposing .table/.rpc/.schema
  - fake_supabase - pytest fixture yielding a fresh client
  - patch_supabase_client - pytest fixture wiring fake into pg_settings
"""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Any, Iterable

import pytest


@dataclass
class FakeSupabaseResponse:
    """Mirrors the subset of ``supabase.APIResponse`` used in production."""

    data: Any = field(default_factory=list)
    count: int | None = None


@dataclass
class _RecordedCall:
    """Single recorded builder-chain invocation used for assertions."""

    table: str | None
    verb: str  # "select" | "insert" | "update" | "delete" | "rpc"
    payload: Any  # select cols / insert rows / update fields / rpc args
    filters: dict[str, Any]
    schema: str | None = None


class FakeSupabaseQuery:
    """Builder-chain fake. Every method returns ``self`` so chains compose."""

    def __init__(self, client: "FakeSupabaseClient", table: str | None, schema: str | None = None):
        self._client = client
        self._table = table
        self._schema = schema
        self._verb: str | None = None
        self._payload: Any = None
        self._filters: dict[str, Any] = {}

    # --- verbs -----------------------------------------------------------

    def select(self, *columns: str, **_: Any) -> "FakeSupabaseQuery":
        self._verb = "select"
        self._payload = columns[0] if len(columns) == 1 else columns or "*"
        return self

    def insert(self, payload: Any, **_: Any) -> "FakeSupabaseQuery":
        self._verb = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict, **_: Any) -> "FakeSupabaseQuery":
        self._verb = "update"
        self._payload = payload
        return self

    def upsert(self, payload: Any, **_: Any) -> "FakeSupabaseQuery":
        self._verb = "upsert"
        self._payload = payload
        return self

    def delete(self, **_: Any) -> "FakeSupabaseQuery":
        self._verb = "delete"
        return self

    # --- filters ---------------------------------------------------------

    def eq(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"eq:{column}"] = value
        return self

    def neq(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"neq:{column}"] = value
        return self

    def gt(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"gt:{column}"] = value
        return self

    def gte(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"gte:{column}"] = value
        return self

    def lt(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"lt:{column}"] = value
        return self

    def lte(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"lte:{column}"] = value
        return self

    def like(self, column: str, pattern: str) -> "FakeSupabaseQuery":
        self._filters[f"like:{column}"] = pattern
        return self

    def in_(self, column: str, values: Iterable[Any]) -> "FakeSupabaseQuery":
        self._filters[f"in:{column}"] = list(values)
        return self

    def is_(self, column: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"is:{column}"] = value
        return self

    def filter(self, column: str, op: str, value: Any) -> "FakeSupabaseQuery":
        self._filters[f"{op}:{column}"] = value
        return self

    def order(self, column: str, **_: Any) -> "FakeSupabaseQuery":
        self._filters[f"order:{column}"] = _
        return self

    def limit(self, n: int) -> "FakeSupabaseQuery":
        self._filters["limit"] = n
        return self

    def single(self) -> "FakeSupabaseQuery":
        self._filters["single"] = True
        return self

    def maybe_single(self) -> "FakeSupabaseQuery":
        self._filters["maybe_single"] = True
        return self

    # --- terminal --------------------------------------------------------

    def execute(self) -> FakeSupabaseResponse:
        verb = self._verb or "select"
        call = _RecordedCall(
            table=self._table,
            verb=verb,
            payload=self._payload,
            filters=dict(self._filters),
            schema=self._schema,
        )
        self._client.calls.append(call)

        # Lookup by (table, verb) preferred; fall back to (table,) wildcard.
        key = (self._table, verb)
        if key in self._client._responses:
            response = self._client._responses[key]
        elif (self._table, "*") in self._client._responses:
            response = self._client._responses[(self._table, "*")]
        else:
            response = self._client._default_response
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(call)
        return response


class FakeSupabaseClient:
    """Top-level fake replacing ``pg_settings.client`` (a ``supabase.Client``)."""

    def __init__(self) -> None:
        self.calls: list[_RecordedCall] = []
        self.rpc_calls: list[_RecordedCall] = []
        self._responses: dict[tuple, Any] = {}
        self._rpc_responses: dict[str, Any] = {}
        self._default_response = FakeSupabaseResponse(data=[], count=0)
        self._default_rpc_response = FakeSupabaseResponse(data=None, count=0)

    # --- registration ---------------------------------------------------

    def register(
        self,
        *,
        table: str,
        verb: str = "*",
        response: FakeSupabaseResponse | Exception | Any,
    ) -> None:
        """Register a canned response for a ``(table, verb)`` pair."""
        self._responses[(table, verb)] = response

    def register_rpc(
        self,
        name: str,
        response: FakeSupabaseResponse | Exception | Any,
    ) -> None:
        """Register a canned response for an RPC call by name."""
        self._rpc_responses[name] = response

    # --- builder entry points -------------------------------------------

    def table(self, name: str) -> FakeSupabaseQuery:
        return FakeSupabaseQuery(self, table=name)

    def from_(self, name: str) -> FakeSupabaseQuery:  # supabase alias
        return self.table(name)

    def rpc(self, name: str, args: dict | None = None) -> "FakeSupabaseRPC":
        return FakeSupabaseRPC(self, name, args or {})

    def schema(self, name: str) -> "FakeSupabaseSchema":
        return FakeSupabaseSchema(self, name)


class FakeSupabaseSchema:
    """Returned by ``client.schema('foo')``; produces tables in that schema."""

    def __init__(self, client: FakeSupabaseClient, schema: str) -> None:
        self._client = client
        self._schema = schema

    def table(self, name: str) -> FakeSupabaseQuery:
        return FakeSupabaseQuery(self._client, table=name, schema=self._schema)

    def rpc(self, name: str, args: dict | None = None) -> "FakeSupabaseRPC":
        return FakeSupabaseRPC(self._client, name, args or {}, schema=self._schema)


class FakeSupabaseRPC:
    """Builder for ``client.rpc('fn', args).execute()``."""

    def __init__(
        self,
        client: FakeSupabaseClient,
        name: str,
        args: dict,
        schema: str | None = None,
    ) -> None:
        self._client = client
        self._name = name
        self._args = args
        self._schema = schema

    def execute(self) -> FakeSupabaseResponse:
        call = _RecordedCall(
            table=None,
            verb="rpc",
            payload={"name": self._name, "args": self._args},
            filters={},
            schema=self._schema,
        )
        self._client.calls.append(call)
        self._client.rpc_calls.append(call)
        response = self._client._rpc_responses.get(
            self._name, self._client._default_rpc_response
        )
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(call)
        return response


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_supabase() -> FakeSupabaseClient:
    """Fresh in-memory Supabase client with no canned responses."""
    return FakeSupabaseClient()


@pytest.fixture
def patch_supabase_client(monkeypatch, fake_supabase) -> FakeSupabaseClient:
    """Wire ``fake_supabase`` into config and already-imported module globals."""
    from config import pg_setting

    # ``client`` is a property on ``PgSetting`` returning a fresh client each
    # time. We replace the property at the class level with a constant.
    monkeypatch.setattr(
        pg_setting.PgSetting,
        "client",
        property(lambda self: fake_supabase),
        raising=True,
    )

    # Some modules import ``client_ordelo`` directly as a name.
    monkeypatch.setattr(pg_setting, "client_ordelo", fake_supabase, raising=False)

    # Replace it inside the top-level ``config`` package too if already bound.
    import config as _config

    monkeypatch.setattr(_config, "client_ordelo", fake_supabase, raising=False)

    # Several modules bind ``from config import client_ordelo`` at import time.
    # If they are already imported before this fixture is requested, patch their
    # module globals as well so tests still use the fake.
    for module in list(sys.modules.values()):
        if module is None:
            continue
        if hasattr(module, "client_ordelo"):
            monkeypatch.setattr(module, "client_ordelo", fake_supabase, raising=False)
    return fake_supabase
