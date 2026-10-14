"""Local dev WITHOUT a public URL:  uv run --project tgram_starter python -m tgram_starter.polling   (from the repo root)
Polling and webhooks are mutually exclusive - this deletes any webhook set on the bot."""
import asyncio

from .bot_factory import build_bot, build_dispatcher
from .config import get_settings


async def main():
    s = get_settings()
    bot, dp = build_bot(s), build_dispatcher(s)
    await bot.delete_webhook(drop_pending_updates=False)
    me = await bot.get_me()
    print(f"Polling as @{me.username} (id {me.id}). Ctrl+C to stop.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
