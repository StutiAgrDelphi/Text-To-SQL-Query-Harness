import asyncio
from agent import build_agent

async def main():
    agent = build_agent()
    session = agent.create_session()
    print("Text-to-SQL assistant ready. Type 'exit' to quit.\n")
    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit", "bye"):
            break
        if not q:
            continue
        # main.py
        try:
            result = await agent.run(q, session=session)
            print(f"\nAssistant: {result.text}\n")
        except Exception as e:
            print(f"\nAssistant: I can't process that request — it was flagged by the platform's safety system. Please rephrase.\n", e)

if __name__ == "__main__":
    asyncio.run(main())