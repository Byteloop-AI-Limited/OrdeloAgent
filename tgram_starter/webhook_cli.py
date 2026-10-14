"""Webhook admin:  python -m tgram_starter.webhook_cli {me|set|info|delete}"""
import asyncio
import sys

from .bot_factory import build_bot, build_dispatcher
from .config import get_settings


async def main(cmd: str):
    s = get_settings()
    bot = build_bot(s)
    try:
        if cmd == "me":
            me = await bot.get_me()
            print(f"OK token valid -> @{me.username} id={me.id} name={me.first_name!r}")
        elif cmd == "set":
            dp = build_dispatcher(s)
            await bot.set_webhook(
                s.webhook_url,
                secret_token=s.webhook_secret,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            print("webhook set ->", s.webhook_url)
        elif cmd == "info":
            print((await bot.get_webhook_info()).model_dump_json(indent=2, exclude_none=True))
        elif cmd == "delete":
            await bot.delete_webhook(drop_pending_updates=False)
            print("webhook deleted")
        else:
            print(__doc__)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
