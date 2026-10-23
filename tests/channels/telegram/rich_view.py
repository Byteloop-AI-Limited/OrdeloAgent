"""Read a rich message back as plain text and buttons, so tests assert what an admin would see, not the aiogram tree."""

from __future__ import annotations

from aiogram.methods import SendMessage, SendRichMessage
from aiogram.types import InputRichMessage


def _flat(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_flat(v) for v in value)
    if value.get("type") == "date_time":
        return "⟨when⟩"
    return _flat(value.get("text"))


def _walk(block: dict, lines: list[str], buttons: list[dict]) -> None:
    kind = block.get("type")
    if kind == "buttons":
        for b in block["buttons"]:
            buttons.append(b)
            lines.append(f"[{b['text']}]")
    elif kind == "details":
        lines.append(_flat(block["summary"]))
        for inner in block["blocks"]:
            _walk(inner, lines, buttons)
    else:
        lines.append(_flat(block.get("text")))


def _read(message: InputRichMessage) -> tuple[list[str], list[dict]]:
    lines: list[str] = []
    buttons: list[dict] = []
    for block in message.model_dump(mode="json", exclude_none=True)["blocks"]:
        _walk(block, lines, buttons)
    return lines, buttons


def rich_text(message: InputRichMessage) -> str:
    return "\n".join(_read(message)[0])


def rich_buttons_of(message: InputRichMessage) -> list[dict]:
    """Every button (dicts with text, style, and either callback_data or disabled), in message order."""
    return _read(message)[1]


def text_of(call) -> str:
    """The text an admin sees in a send or an edit: the rich form if there is one, else the HTML text."""
    rich = getattr(call, "rich_message", None)
    return rich_text(rich) if rich is not None else (call.text or "")


def button_data_of(call) -> list[str]:
    """callback_data of every tappable button, whether it is embedded in a rich message or in an inline keyboard."""
    rich = getattr(call, "rich_message", None)
    if rich is not None:
        return [b["callback_data"] for b in rich_buttons_of(rich) if "callback_data" in b]
    markup = getattr(call, "reply_markup", None)
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup is not None else []


def all_sends(session) -> list:
    """Every message sent, HTML or rich (RecordingSession.sends counts only the HTML ones)."""
    return [c for c in session.calls if isinstance(c, (SendMessage, SendRichMessage))]
