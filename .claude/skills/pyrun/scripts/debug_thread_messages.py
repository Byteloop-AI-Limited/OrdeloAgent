import argparse
import asyncio

from ordelo.agents.agent_runner import debug_thread


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print message content for a thread via debug_thread."
    )
    parser.add_argument("thread_id", help="Thread ID to inspect, e.g. ELAS-...")
    args = parser.parse_args()

    res = await debug_thread(args.thread_id, full_state=True)
    for item in res.get("messages", []):
        content = getattr(item, "content", None)
        if content is not None:
            print(content)


if __name__ == "__main__":
    asyncio.run(main())
