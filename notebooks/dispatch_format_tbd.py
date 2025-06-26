import asyncio
from config import pg_settings
from ordelo.agents.rider_agent import builder
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from utils_common.lg_utils import get_config_for_recipient


async def get_last_msg_ts(graph, recipient=None, thread_id=None):
    """
    Returns the created_at timestamp for the latest state snapshot for a given recipient or thread_id.
    Provide either recipient or thread_id (recipient takes precedence if both are provided).
    """
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)

    if recipient is not None:
        config = await get_config_for_recipient(recipient, pool)
    elif thread_id is not None:
        config = {"configurable": {"thread_id": thread_id}}
    else:
        raise ValueError("Either recipient or thread_id must be provided.")

    state = await graph.aget_state(config=config)
    # created_at is a top-level attribute on the state snapshot
    return getattr(state, "created_at", None)


# Example usage (uncomment to run in notebook):
# ts = asyncio.run(get_last_msg_ts(recipient="447448440754"))
# print(ts)
