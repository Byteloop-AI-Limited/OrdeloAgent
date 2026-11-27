"""ADR 0019 guard: Postgres owns every schedule, so the FastAPI lifespan starts no polling loop.

Fails if `lifespan` in watomation/fapp_ordelo_agent.py contains a `while True` loop or an `asyncio.create_task` call, or if
any module under channels/, utils_common/ or ordelo/ defines `run_sweeper`.

PHASE 1 ALLOWANCE (plans/telegram-rider-invite-alert-schedule.md): the customer notifier loop is still started from the
lifespan (`asyncio.create_task(run_sweeper())`) and still defined in utils_common/notify/customer_notifier.py. Phase 2 moves
it to pg_cron and must delete both allowances below.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "watomation" / "fapp_ordelo_agent.py"

ALLOWED_TASKS = {"run_sweeper"}  # phase 1 allowance: customer_notifier.run_sweeper (remove in phase 2)
ALLOWED_RUN_SWEEPER = {"utils_common/notify/customer_notifier.py"}  # phase 1 allowance (remove in phase 2)


def _lifespan() -> ast.AsyncFunctionDef:
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    found = [n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "lifespan"]
    assert len(found) == 1, "watomation/fapp_ordelo_agent.py must define exactly one lifespan"
    return found[0]


def _is_create_task(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr in ("create_task", "ensure_future")) or (
        isinstance(f, ast.Name) and f.id in ("create_task", "ensure_future"))


def _task_target(call: ast.Call) -> str | None:
    arg = call.args[0] if call.args else None
    if isinstance(arg, ast.Call):
        f = arg.func
        return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    return None


def test_lifespan_has_no_while_true_loop():
    loops = [n for n in ast.walk(_lifespan()) if isinstance(n, ast.While)
             and isinstance(n.test, ast.Constant) and n.test.value is True]
    assert not loops, "lifespan must not poll (ADR 0019): schedule the work with pg_cron"


def test_lifespan_starts_no_background_task_except_the_phase_1_allowance():
    tasks = [n for n in ast.walk(_lifespan()) if isinstance(n, ast.Call) and _is_create_task(n)]
    targets = [_task_target(t) for t in tasks]
    unexpected = [t for t in targets if t not in ALLOWED_TASKS]
    assert not unexpected, f"lifespan starts background tasks {unexpected}; schedule them with pg_cron (ADR 0019)"
    assert "run_rider_invite_alerts" not in APP.read_text(encoding="utf-8")


def test_no_module_defines_run_sweeper():
    offenders = []
    for top in ("channels", "utils_common", "ordelo"):
        for p in (ROOT / top).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "run_sweeper" for n in ast.walk(tree)):
                if rel not in ALLOWED_RUN_SWEEPER:
                    offenders.append(rel)
    assert not offenders, f"in-process sweep loops are not allowed (ADR 0019): {offenders}"
