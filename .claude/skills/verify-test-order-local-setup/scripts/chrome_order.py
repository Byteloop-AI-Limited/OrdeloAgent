#!/usr/bin/env python3
"""Drive the Strikers web storefront and the owner's Telegram Web chats through agent-desktop (headless).

Standard library only; no application import, no network call, no database access. Every action is an accessibility
press or set-value on one freshly found element. Usage (see ../SKILL.md):

  chrome_order.py windows
  chrome_order.py open URL                                  open URL in a NEW Chrome window, print its window id
  chrome_order.py close WIN                                 close a window this run opened
  chrome_order.py dump WIN [--grep RE]                      text and controls of the visible page
  chrome_order.py click WIN ROLE NAME                       press the only element with this role and exact name
  chrome_order.py order Collection|Delivery [--qty 2] [--review-only]
                                                            new window: TEST3100 x qty -> review -> Simulate payment;
                                                            prints "ORDER WIN" (WIN = its tracking page)
  chrome_order.py watch-page WIN SECONDS                    print the tracking page's wording as it changes
  chrome_order.py tg-read WIN BOT [--tail 30]
  chrome_order.py tg-tap WIN BOT ORDER LABEL_RE             press a button belonging to ORDER in the open bot chat
  chrome_order.py tg-say WIN BOT TEXT                       type TEXT into the open bot chat and send it
"""
import argparse
import json
import re
import subprocess
import sys
import time

APP = "Google Chrome"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
STORE = "https://restaurant-test.ordelo.app/town/orpington/strk"
BOTS = ("OrdeloRestaurantBot", "ByteloopRidersBot")
ORDER_RE = re.compile(r"\b[A-Z]{4}-[A-Z]{4}-\d{2,3}\b")
TEST_NOTICE = "This is a test order"
TEST_ITEM = "TEST3100"


def die(message):
    print("STOP:", message)
    sys.exit(1)


def ad(*args, check=True):
    """Run agent-desktop and return its data. Never retries an action."""
    run = subprocess.run(["agent-desktop", *args], capture_output=True, text=True)
    try:
        body = json.loads(run.stdout)
    except ValueError:
        die(f"agent-desktop {args[0]}: {run.stdout[:200]} {run.stderr[:200]}")
    if check and not body.get("ok"):
        die(f"agent-desktop {args[0]}: {json.dumps(body.get('error'))[:400]}")
    return body.get("data") or {}


def flat(node, out=None):
    out = [] if out is None else out
    out.append(node)
    for child in node.get("children", []):
        flat(child, out)
    return out


def text(node):
    parts = [str(node.get(k) or "").replace("\n", " ").strip() for k in ("name", "value")]
    return " | ".join(dict.fromkeys(p for p in parts if p))


def snapshot(win, *extra):
    # No --compact: it drops the confirmation countdown (role="timer").
    return flat(ad("snapshot", "--window-id", win, "--max-depth", "50", "--timeout-ms", "30000", *extra)["tree"])


def windows():
    return [w["id"] for w in ad("list-windows", "--app", APP)]


def focus(win):
    # A window hidden behind another stops rendering, so its tree goes stale or empty.
    ad("focus-window", "--window-id", win)
    time.sleep(1.5)


def url(nodes):
    return next((n.get("value") or "" for n in nodes if (n.get("name") or "").startswith("Address and search")), "")


def page(win):
    """Nodes inside the (single) page of the window, plus its URL."""
    nodes = snapshot(win)
    areas = [n for n in nodes if n.get("role") == "webarea"]
    if len(areas) != 1:
        die(f"{win}: expected one page, found {len(areas)} (loading, hidden, or a split view)")
    return flat(areas[0]), url(nodes)


def press(win, role, name):
    nodes, _ = page(win)
    hits = [n for n in nodes if n.get("role") == role and (n.get("name") or "").strip() == name and n.get("ref_id")]
    if len(hits) != 1:
        die(f"{len(hits)} {role} named {name!r} in {win}")
    ad("click", hits[0]["ref_id"])


def wait_for(win, predicate, seconds, what):
    end = time.time() + seconds
    while time.time() < end:
        nodes = snapshot(win)
        if predicate(nodes):
            return nodes
        time.sleep(0.7)
    die(f"{win}: {what} did not appear in {seconds}s")


def has(role, name):
    return lambda nodes: any(n.get("role") == role and (n.get("name") or "").strip() == name for n in nodes)


def open_window(address):
    """A new window, never a tab: Chrome puts tabs in whichever window it thinks was used last."""
    before = set(windows())
    subprocess.run([CHROME, "--new-window", address], capture_output=True)
    end = time.time() + 15
    while time.time() < end:
        new = [w for w in windows() if w not in before]
        if new:
            time.sleep(5)
            return new[0]
        time.sleep(0.5)
    die("no new Chrome window")


def cmd_open(a):
    print(open_window(a.url))


def cmd_close(a):
    nodes = snapshot(a.win)
    if sum(n.get("role") == "webarea" for n in nodes) > 1:
        die("split view: this is the owner's window")
    hits = [n for n in nodes if n.get("role") == "button" and n.get("name") == "Close" and n.get("ref_id")]
    if not hits:
        die("no window Close button")
    ad("click", hits[-1]["ref_id"])


def cmd_dump(a):
    nodes, where = page(a.win)
    print("URL", re.sub(r"(activate|/o)/[\w-]+", r"\1/***", where))
    for n in nodes:
        line = f"{n.get('role')} {n.get('ref_id', '')} {text(n)[:200]} {n.get('states') or ''}"
        if text(n) and (not a.grep or re.search(a.grep, line, re.I)):
            print(re.sub(r"(activate|/o)/[\w-]+", r"\1/***", line))


def test_basket_quantity(win):
    nodes, _ = page(win)
    if not has("heading", "Your basket")(nodes):
        die(f"{win}: open the STRK basket before continuing")
    buttons = [(i, (n.get("name") or "").strip()) for i, n in enumerate(nodes) if n.get("role") == "button"]
    remove_buttons = [name for _, name in buttons if name.startswith("Remove ")]
    if remove_buttons != [f"Remove {TEST_ITEM}"]:
        die(f"{win}: the basket must contain only {TEST_ITEM}; inspect it before continuing")
    decrease = next((i for i, name in buttons if name == f"Decrease {TEST_ITEM} quantity"), None)
    increase = next((i for i, name in buttons if name == f"Increase {TEST_ITEM} quantity"), None)
    if decrease is not None and increase is not None and decrease < increase:
        quantities = [text(n) for n in nodes[decrease + 1:increase] if n.get("role") == "statictext"]
        if len(quantities) == 1 and re.fullmatch(r"[1-9][0-9]*", quantities[0]):
            return int(quantities[0])
    die(f"{win}: could not read the {TEST_ITEM} basket quantity")


def cmd_order(a):
    if a.qty < 1:
        die("order quantity must be at least one")
    win = open_window(STORE)
    wait_for(win, has("checkbox", a.mode), 20, "storefront")
    time.sleep(2)
    nodes, where = page(win)
    if "/town/orpington/strk" not in where:
        die("storefront tab is not in this window: " + where)
    press(win, "checkbox", a.mode)
    time.sleep(1)
    nodes, _ = page(win)
    if not has("button", "View basket")(nodes):
        press(win, "button", f"Add {TEST_ITEM}")
        wait_for(win, has("button", "View basket"), 10, "basket")
    press(win, "button", "View basket")
    wait_for(win, has("heading", "Your basket"), 10, "open basket")
    quantity = test_basket_quantity(win)
    for _ in range(abs(a.qty - quantity)):
        if quantity == a.qty:
            break
        adjustment = "Increase" if quantity < a.qty else "Decrease"
        press(win, "button", f"{adjustment} {TEST_ITEM} quantity")
        time.sleep(0.8)
        quantity = test_basket_quantity(win)
    if quantity != a.qty:
        die(f"{win}: expected {TEST_ITEM} × {a.qty} before checkout")
    press(win, "button", "Go to checkout")
    wait_for(win, has("button", "Continue to review"), 25, "checkout")
    if a.mode == "Delivery":
        nodes, _u = page(win)
        house = [n for n in nodes if n.get("role") == "textfield" and "house number" in (n.get("name") or "") and n.get("ref_id")]
        if len(house) != 1:
            die("house number field not found; set a delivery postcode on the storefront first")
        if not house[0].get("value"):
            ad("set-value", house[0]["ref_id"], a.house)
    nodes, _ = page(win)
    order_lines = [text(n) for n in nodes if n.get("role") == "statictext" and re.match(r"^\d+\s*×\s+", text(n))]
    if order_lines != [f"{a.qty} × {TEST_ITEM}"]:
        die(f"{win}: checkout must show only {TEST_ITEM} × {a.qty} before review")
    press(win, "button", "Continue to review")
    nodes = wait_for(win, has("button", "Simulate payment"), 25, "Simulate payment")
    if not any(TEST_NOTICE in text(n) for n in nodes):
        die("the review page does not say this is a test order")
    if a.review_only:
        print("at-review", win)
        return
    press(win, "button", "Simulate payment")
    end = time.time() + 25
    while time.time() < end:
        where = url(snapshot(win))
        found = re.search(r"orders/([A-Z]{4}-[A-Z]{4}-\d+)", where)
        if found:
            print(found[1], win)
            return
        time.sleep(0.7)
    die("no order page; look up the order in the database before retrying")


def cmd_watch_page(a):
    focus(a.win)
    end, last = time.time() + a.seconds, None
    rx = re.compile(r"^\d:\d\d$|Time left|Checking with|accept|declin|cancel|releas|refund|Waiting for|Ready around|On its way|Delivered|Rider", re.I)
    while time.time() < end:
        nodes = snapshot(a.win)
        seen = [text(n) for n in nodes if n.get("role") in ("heading", "statictext")]
        keep = [t for t in dict.fromkeys(seen) if rx.search(t)]
        key = [re.sub(r"^\d:\d\d$", "m:ss", t) for t in keep]
        if key != last:
            print(time.strftime("%H:%M:%S"), keep, flush=True)
            last = key
        time.sleep(1)


def chat(win, bot):
    if bot not in BOTS:
        die(f"only {BOTS} may be driven")
    nodes, where = page(win)
    if not where.rstrip("/").endswith("#@" + bot):
        die(f"{win} is not the {bot} chat: {where}")
    links = [i for i, n in enumerate(nodes) if n.get("role") == "link" and text(n).startswith(BOTS)]
    start = links[-1] + 1 if links else 0
    return [n for n in nodes[start:] if n.get("role") in ("statictext", "button", "link", "textfield") and text(n)]


def cmd_tg_read(a):
    focus(a.win)
    for n in chat(a.win, a.bot)[-a.tail:]:
        print(n["role"], n.get("ref_id", ""), text(n)[:300])


def cmd_tg_tap(a):
    focus(a.win)
    end, hits = time.time() + a.wait, []
    while not hits and time.time() < end:  # job_t_order_alerts sends about 5 s after payment
        current, hits = None, []
        for n in chat(a.win, a.bot):
            if n["role"] != "button":
                found = ORDER_RE.search(text(n))
                current = found[0] if found else current
            elif current == a.order and n.get("ref_id") and re.search(a.label, text(n).strip()):
                hits.append(n)
        time.sleep(0 if hits else 1)
    if not hits:
        die(f"no button matching {a.label!r} under {a.order}")
    print("tapping:", text(hits[-1]))
    ad("click", hits[-1]["ref_id"])


def cmd_tg_say(a):
    focus(a.win)
    box = [n for n in chat(a.win, a.bot) if n["role"] == "textfield" and n.get("ref_id")]
    if len(box) != 1:
        die(f"{len(box)} message boxes")
    ad("set-value", box[0]["ref_id"], a.text)
    time.sleep(1)
    send = [n for n in chat(a.win, a.bot) if n["role"] == "button" and text(n).strip() == "Send"]
    if len(send) != 1:
        die("no Send button; the text was not accepted")
    ad("click", send[0]["ref_id"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("windows").set_defaults(fn=lambda a: print("\n".join(windows())))

    def add(name, fn, *positional):
        s = sub.add_parser(name)
        for arg in positional:
            s.add_argument(arg)
        s.set_defaults(fn=fn)
        return s

    add("open", cmd_open, "url")
    add("close", cmd_close, "win")
    add("dump", cmd_dump, "win").add_argument("--grep")
    add("click", lambda a: (focus(a.win), press(a.win, a.role, a.name)), "win", "role", "name")
    s = sub.add_parser("order")
    s.add_argument("mode", choices=("Collection", "Delivery"))
    s.add_argument("--qty", type=int, default=2)
    s.add_argument("--house", default="1")
    s.add_argument("--review-only", action="store_true", help="stop before payment; the order exists and is unpaid")
    s.set_defaults(fn=cmd_order)
    s = sub.add_parser("watch-page")
    s.add_argument("win")
    s.add_argument("seconds", type=float)
    s.set_defaults(fn=cmd_watch_page)
    add("tg-read", cmd_tg_read, "win", "bot").add_argument("--tail", type=int, default=30)
    add("tg-tap", cmd_tg_tap, "win", "bot", "order", "label").add_argument("--wait", type=float, default=15)
    add("tg-say", cmd_tg_say, "win", "bot", "text")
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
