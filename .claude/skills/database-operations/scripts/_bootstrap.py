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


def get_client_ordelo(schema: Optional[str] = None):
    ensure_repo_on_path()
    from config import pg_settings  # type: ignore

    client_ordelo = pg_settings.client
    return client_ordelo.schema(schema) if schema else client_ordelo


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
