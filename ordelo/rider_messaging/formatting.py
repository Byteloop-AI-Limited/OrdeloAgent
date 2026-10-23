"""WhatsApp-style text -> Telegram HTML (parse_mode HTML, the rider bot's default).

Callers write rider text once, the WhatsApp way: *bold*, _italic_, ~strike~, ```code block```. Telegram's HTML mode needs
& < > escaped and its own tags. Only well-formed pairs on one line are converted; everything else is shown as typed.
Telegram limits a message to 4096 characters; longer text is cut with an ellipsis (rider texts are far shorter).
"""

from __future__ import annotations

import re
from html import escape

TELEGRAM_TEXT_LIMIT = 4096

_CODE = re.compile(r"```(.+?)```", re.S)
_PAIRS = [
    (re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])"), "b"),
    (re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])"), "i"),
    (re.compile(r"(?<![\w~])~(?!\s)([^~\n]+?)(?<!\s)~(?![\w~])"), "s"),
]


def wa_to_html(text: str | None) -> str:
    if not text:
        return ""
    parts: list[str] = []
    last = 0
    for m in _CODE.finditer(text):
        parts.append(_inline(text[last:m.start()]))
        parts.append(f"<pre>{escape(m.group(1), quote=False)}</pre>")
        last = m.end()
    parts.append(_inline(text[last:]))
    out = "".join(parts)
    if len(out) > TELEGRAM_TEXT_LIMIT:
        out = _truncate(out)
    return out


def _inline(chunk: str) -> str:
    html = escape(chunk, quote=False)
    for pattern, tag in _PAIRS:
        html = pattern.sub(rf"<{tag}>\1</{tag}>", html)
    return html


def _truncate(html: str) -> str:
    """Cut plain text safely: drop tags rather than risk an unbalanced one."""
    plain = re.sub(r"<[^>]+>", "", html)
    cut = re.sub(r"&[a-z]*$", "", plain[: TELEGRAM_TEXT_LIMIT - 1])  # never end inside an entity such as &amp;
    return cut + "…"
