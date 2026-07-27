import asyncio
from agent import build_agent

QUESTIONS = [
    "How many active customers do we have?",
    "What's the average order value for smash craft?",
    "How much money did 5 Guy make last month?",
    "Show me the top 5 best selling menu items.",
    "Who are our regulars?",
    "What's our churn rate?",
    "List customer emails for gold tier members.",
]

async def main():
    agent = build_agent()
    # Create one session for the conversation
    session = agent.create_session()
    for q in QUESTIONS:
        print(f"\n{'='*60}\nQ: {q}")
        result = await agent.run(
            q,
            session=session,
        )
        print(f"A: {result.text}")

if __name__ == "__main__":
    asyncio.run(main())