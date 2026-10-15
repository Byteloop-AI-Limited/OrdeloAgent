import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "config" / "__init__.py").exists() and (path / "config").is_dir()


def ensure_repo_on_path() -> Path:
    candidates: list[Path] = []

    env_root = os.environ.get("ORDELO_REPO_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())

    cwd = Path.cwd()
    candidates.append(cwd)
    candidates.extend(cwd.parents)

    for candidate in candidates:
        candidate = candidate.resolve()
        if _looks_like_repo_root(candidate):
            sys.path.insert(0, str(candidate))
            return candidate

    raise RuntimeError(
        "Could not locate OrdeloAgent repo root. Run from the repo root or set ORDELO_REPO_ROOT."
    )


# Postgres 42501 = permission denied / RLS violation; PGRST301/302 = JWT / role problems.
PERMISSION_ERROR_CODES = {"42501", "PGRST301", "PGRST302"}


def execute_with_fallback(build, schema: Optional[str] = None, *, service: bool = False):
    """Run `build(client).execute()`-style callable: anon `client_ordelo` first, service role only on a permission error.

    `build` receives a Supabase client and must return the executed response.
    Pass service=True to skip the anon attempt (e.g. when RLS silently returns zero rows instead of erroring).
    """
    ensure_repo_on_path()
    from config import client_ordelo, client_ordelo_service  # type: ignore
    from postgrest.exceptions import APIError  # type: ignore

    def scoped(client):
        return client.schema(schema) if schema else client

    if service:
        return build(scoped(client_ordelo_service))
    try:
        return build(scoped(client_ordelo))
    except APIError as exc:
        if exc.code not in PERMISSION_ERROR_CODES:
            raise
        print(
            f"[db-ops] anon client_ordelo denied ({exc.code}: {exc.message}); retrying with the service-role key",
            file=sys.stderr,
        )
        return build(scoped(client_ordelo_service))


def load_json(*, json_str: Optional[str], json_file: Optional[str]) -> Any:
    if json_str and json_file:
        raise ValueError("Use only one of --json or --json-file.")
    if json_file:
        return json.loads(Path(json_file).read_text(encoding="utf-8"))
    if json_str:
        return json.loads(json_str)
    raise ValueError("Provide --json or --json-file.")


def coerce_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


def parse_key_value(pairs: list[str]) -> list[tuple[str, Any]]:
    parsed: list[tuple[str, Any]] = []
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Expected key=value, got: {item!r}")
        key, raw = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Empty key in: {item!r}")
        parsed.append((key, coerce_scalar(raw.strip())))
    return parsed
