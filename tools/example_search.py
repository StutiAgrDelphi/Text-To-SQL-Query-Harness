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

TOP_K = 3


def embed(text: str):
    resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding


@tool(approval_mode="never_require")
def search_example_sql(
    query: Annotated[str, Field(description="The user's question, used to find similar previously-solved questions and their correct SQL.")],
) -> str:
    vec = embed(query)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT question, sql, 1 - (embedding <=> %s::vector) AS sim "
                "FROM example_sql_catalog ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, vec, TOP_K),
            )
            rows = cur.fetchall()
        if not rows:
            return "No similar examples found."
        return "\n\n".join(f"Q: {q}\nSQL: {sql}" for q, sql, _ in rows)
    finally:
        conn.close()