# %%
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage

# %%


async def main():
    # Agentic loop: streams messages as Claude works
    async for message in query(
        prompt="tell me a joke",
        options=ClaudeAgentOptions(
            allowed_tools=["Read"],  # Tools Claude can use
            permission_mode="acceptEdits",  # Auto-approve file edits
        ),
    ):
        # Print human-readable output
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)  # Claude's reasoning
                elif hasattr(block, "name"):
                    print(f"Tool: {block.name}")  # Tool being called
        elif isinstance(message, ResultMessage):
            print(f"Done: {message.subtype}")  # Final result


# %%
from dotenv import load_dotenv

load_dotenv("../../.env_openrouter", override=True)

# %%
# asyncio.run(main())
await main()