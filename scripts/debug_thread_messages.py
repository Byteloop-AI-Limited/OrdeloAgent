#!/usr/bin/env python
import asyncio
import json
import sys

from ordelo.agents.agent_runner import debug_thread


def extract_role_and_content(message: dict) -> dict:
    if not message:
        return {"role": None, "content": None}
    role = next(iter(message.keys()))
    content = message.get(role, {}).get("content")
    return {"role": role, "content": content}


async def main(thread_id: str) -> None:
    data = await debug_thread(thread_id)
    messages = data.get("messages", [])
    ordered = list(reversed(messages))
    output = [extract_role_and_content(msg) for msg in ordered]
    print(json.dumps(output, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_thread_messages.py <thread_id>")
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1]))
