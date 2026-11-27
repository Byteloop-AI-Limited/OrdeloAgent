"""ADR 0019 guard: Postgres owns every schedule, so the FastAPI lifespan starts no polling loop.

In watomation/fapp_ordelo_agent.py, `lifespan` and every module-level function it calls (directly or through other
helpers, its "helpers") must contain no `while True` loop and no `create_task` / `ensure_future` call. No module under
watomation/ may run a `while True` loop at module level, and no module under channels/, utils_common/, ordelo/ or
watomation/ may define `run_sweeper`.

PHASE 1 ALLOWANCE (plans/telegram-rider-invite-alert-schedule.md): the customer notifier loop is still started from the
lifespan and still defined in utils_common/notify/customer_notifier.py. The allowance is exactly one
`asyncio.create_task(run_sweeper())`, written in `lifespan` itself, where `run_sweeper` is imported by
`from utils_common.notify.customer_notifier import run_sweeper` and bound nowhere else in the module. Phase 2 moves the
notifier to pg_cron and must delete both allowances below.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "watomation" / "fapp_ordelo_agent.py"

ALLOWED_TASK = ("utils_common.notify.customer_notifier", "run_sweeper")  # phase 1 allowance (remove in phase 2)
ALLOWED_RUN_SWEEPER = {"utils_common/notify/customer_notifier.py"}  # phase 1 allowance (remove in phase 2)

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


def _bindings_of(tree: ast.Module, name: str) -> list[str]:
    """Every way `name` is bound in the module, as readable strings."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            out += [f"from {n.module} import {a.name}" for a in n.names if (a.asname or a.name) == name]
        elif isinstance(n, ast.Import):
            out += [f"import {a.name}" for a in n.names if (a.asname or a.name.split(".")[0]) == name]
        elif isinstance(n, FUNCS + (ast.ClassDef,)) and n.name == name:
            out.append(f"def {name}")
        elif isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append(f"{name} = ...")
        elif isinstance(n, ast.arg) and n.arg == name:
            out.append(f"argument {name}")
    return out


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


def test_lifespan_starts_only_the_phase_1_customer_notifier_task():
    tree = _tree()
    lifespan = _lifespan(tree)
    everywhere = [(fn.name, c.lineno) for fn in _lifespan_and_helpers(tree) for c in _calls_in(fn)]
    in_lifespan = _calls_in(lifespan)
    assert len(everywhere) == 1 and len(in_lifespan) == 1, (
        f"lifespan and its helpers start background tasks at {everywhere}; only the phase 1 customer notifier task is "
        "allowed. Schedule the work with pg_cron (ADR 0019)")

    call = in_lifespan[0]
    arg = call.args[0] if len(call.args) == 1 and not call.keywords else None
    module, name = ALLOWED_TASK
    assert (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == name
            and not arg.args and not arg.keywords), f"the one allowed task is exactly create_task({name}())"
    assert _bindings_of(tree, name) == [f"from {module} import {name}"], (
        f"{name} must be imported once from {module} and bound nowhere else, found {_bindings_of(tree, name)}")
    assert "run_rider_invite_alerts" not in APP.read_text(encoding="utf-8")


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
                if rel not in ALLOWED_RUN_SWEEPER:
                    offenders.append(rel)
    assert not offenders, f"in-process sweep loops are not allowed (ADR 0019): {offenders}"
