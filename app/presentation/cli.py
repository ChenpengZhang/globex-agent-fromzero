import asyncio

from app.application.agents.orchestrator import (
    SubmitIntentInput,
)
from app.composition import build_container


async def main() -> None:
    container = build_container()

    shopping_session_id = "cli-session"
    buyer_id = "cli-buyer"

    async def talk_to_agent(raw_query: str) -> None:
        intent = SubmitIntentInput(
            shopping_session_id=shopping_session_id,
            buyer_id=buyer_id,
            locale="zh-CN",
            currency="CNY",
            raw_query=raw_query,
        )

        result = await container.orchestrator.handle_intent(
            intent,
        )

        print(f"\nGlobex：{result.final_text}\n")

    # 先让真实模型主动开始会话。
    await talk_to_agent(
        "一个新的购物会话已经开始。"
        "请向顾客打招呼，并只询问顾客想购买什么。"
        "这一步不要调用任何工具。"
    )

    while True:
        raw_query = input("你：").strip()

        if raw_query.casefold() in {
            "exit",
            "quit",
            "退出",
            "结束",
        }:
            print("Globex：再见！")
            break

        if not raw_query:
            continue

        await talk_to_agent(raw_query)


if __name__ == "__main__":
    asyncio.run(main())
    