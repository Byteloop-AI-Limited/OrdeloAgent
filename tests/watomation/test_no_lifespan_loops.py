"""ADR 0019 guard: Postgres owns every schedule, so the FastAPI lifespan starts no polling loop.

In watomation/fapp_ordelo_agent.py, `lifespan` and every module-level function it calls (directly or through other
helpers, its "helpers") must contain no `while True` loop and no `create_task` / `ensure_future` call. No module under
watomation/ may run a `while True` loop at module level, and no module under channels/, utils_common/, ordelo/ or
watomation/ may define `run_sweeper`. There are no allowances: since phase 2 of
plans/telegram-rider-invite-alert-schedule.md the customer notifier sweeps are woken by pg_cron too
(watomation/routers/sweep_hooks.py).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "watomation" / "fapp_ordelo_agent.py"

FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _tree() -> ast.Module:
    return ast.parse(APP.read_text(encoding="utf-8"))


def _lifespan(tree: ast.Module) -> ast.AsyncFunctionDef:
    found = [n for n in ast.walk(tree) if isinstance(n, FUNCS) and n.name == "lifespan"]
    assert len(found) == 1, "watomation/fapp_ordelo_agent.py must define exactly one lifespan"
    return found[0]


def _lifespan_and_helpers(tree: ast.Module) -> list[ast.AST]:
    """lifespan plus every module-level function reachable from it by plain-name calls or references."""
    top = {n.name: n for n in tree.body if isinstance(n, FUNCS)}
    start = _lifespan(tree)
    seen, todo = {start.name}, [start]
    out: list[ast.AST] = []
    while todo:
        fn = todo.pop()
        out.append(fn)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and n.id in top and n.id not in seen:
                seen.add(n.id)
                todo.append(top[n.id])
    return out


def _is_while_true(n: ast.AST) -> bool:
    return isinstance(n, ast.While) and isinstance(n.test, ast.Constant) and bool(n.test.value)


def _is_create_task(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr in ("create_task", "ensure_future")) or (
        isinstance(f, ast.Name) and f.id in ("create_task", "ensure_future"))


def _calls_in(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and _is_create_task(n)]


def test_lifespan_and_its_helpers_have_no_while_true_loop():
    loops = [(fn.name, n.lineno) for fn in _lifespan_and_helpers(_tree()) for n in ast.walk(fn) if _is_while_true(n)]
    assert not loops, f"lifespan must not poll (ADR 0019), found while True at {loops}: schedule the work with pg_cron"


def test_no_watomation_module_loops_at_module_level():
    offenders = []
    for p in (ROOT / "watomation").rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        stack = list(tree.body)
        while stack:   # module-level statements, including those nested in if/try/with/for, but not in def/class
            n = stack.pop()
            if isinstance(n, FUNCS + (ast.ClassDef, ast.Lambda)):
                continue
            if _is_while_true(n):
                offenders.append(f"{p.relative_to(ROOT).as_posix()}:{n.lineno}")
            stack.extend(ast.iter_child_nodes(n))
    assert not offenders, f"module-level while True loops are not allowed (ADR 0019): {offenders}"


def test_lifespan_and_its_helpers_start_no_background_task():
    tree = _tree()
    tasks = [(fn.name, c.lineno) for fn in _lifespan_and_helpers(tree) for c in _calls_in(fn)]
    assert not tasks, (
        f"lifespan and its helpers start background tasks at {tasks}: schedule the work with pg_cron (ADR 0019)")


def test_the_app_no_longer_mentions_the_old_loops():
    text = APP.read_text(encoding="utf-8")
    assert "run_sweeper" not in text and "run_rider_invite_alerts" not in text


def test_no_module_defines_run_sweeper():
    offenders = []
    for top in ("channels", "utils_common", "ordelo", "watomation"):
        for p in (ROOT / top).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            if any(isinstance(n, FUNCS) and n.name == "run_sweeper" for n in ast.walk(tree)):
                offenders.append(rel)
    assert not offenders, f"in-process sweep loops are not allowed (ADR 0019): {offenders}"
