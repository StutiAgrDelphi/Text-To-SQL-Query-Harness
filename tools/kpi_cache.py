import os
from typing import Annotated
from pydantic import Field
from agent_framework import tool
from openai import AzureOpenAI
from db import get_connection

embed_client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_EMBEDDING_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_EMBEDDING_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_EMBEDDING_API_VERSION"],
)
EMBED_DEPLOYMENT = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]

chat_client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)
CHAT_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

AUTO_ACCEPT = 0.92
CONSIDER = 0.65
TOP_K = 3


def embed(text: str):
    resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding


def llm_confirm(user_question: str, candidate_question: str) -> bool:
    prompt = (
        f"User asked: '{user_question}'\n"
        f"A cached KPI answers: '{candidate_question}'\n"
        "Do these ask for the exact same information (same metric, same scope, "
        "same filters)? Reply ONLY 'yes' or 'no'. If there's any meaningful "
        "difference in what's being asked, say no."
    )
    resp = chat_client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return resp.choices[0].message.content.strip().lower().startswith("yes")


@tool(approval_mode="never_require")
def check_kpi_cache(
    question: Annotated[str, Field(description="The user's question, checked against a cache of common pre-computed KPIs before running the full pipeline.")],
) -> str:
    vec = embed(question)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT question, answer, 1 - (embedding <=> %s::vector) AS sim "
                "FROM kpi_catalog ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, vec, TOP_K),
            )
            rows = cur.fetchall()
        if not rows:
            return "NO_CACHE_MATCH — proceed with the full pipeline."

        top_q, top_a, top_sim = rows[0]
        print("Row: ",rows[0])
        if top_sim >= AUTO_ACCEPT:
            return f"CACHE_HIT: {top_a}"
        if top_sim >= CONSIDER and llm_confirm(question, top_q):
            return f"CACHE_HIT: {top_a}"
        return "NO_CACHE_MATCH — proceed with the full pipeline."
    finally:
        conn.close()