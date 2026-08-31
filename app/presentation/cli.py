import asyncio

from agentscope.message import UserMsg

from app.composition import build_container


async def main() -> None:
    container = build_container()

    raw_query = input("你：").strip()
    if not raw_query:
        print("请输入查询内容")
        return

    user_message = UserMsg(name = "buyer", content = raw_query)

    reply = await container.main_agent.reply([user_message])

    final_text = reply.get_text_content() or ""
    print(f"Globex: {final_text}")


if __name__ == "__main__":
    asyncio.run(main())