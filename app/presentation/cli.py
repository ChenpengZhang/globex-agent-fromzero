import asyncio

from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
from app.composition import build_container


async def main() -> None:
    container = build_container()

    raw_query = input("你：").strip()
    if not raw_query:
        print("请输入查询内容")
        return

    intent = SubmitIntentInput(
        shopping_session_id="cli-session",
        buyer_id="cli-buyer",
        locale="zh-CN",
        currency="CNY",
        raw_query=raw_query,
    )

    result = await container.orchestrator.handle_intent(
        intent,
    )

    print(f"Globex: {result.final_text}")


if __name__ == "__main__":
    asyncio.run(main())
    