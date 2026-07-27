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

TOP_K = 10


def embed(text: str):
    resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding


@tool(approval_mode="never_require")
def search_schema(
    query: Annotated[str, Field(description="The user's question, or a short paraphrase of what data is needed, used to semantically find the most relevant tables/columns.")],
) -> str:
    """Stage 5 — schema retrieval. ALWAYS call this near the start of answering a
    question, before writing SQL, to find which tables/columns are actually relevant.
    Returns the closest-matching table/column descriptions from the curated schema
    catalog. Follow up with get_table_schema on the specific tables it returns for
    the exact, full column list before writing SQL — never guess a column name."""
    vec = embed(query)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name, description, 1 - (embedding <=> %s::vector) AS sim "
                "FROM schema_catalog ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, vec, TOP_K),
            )
            rows = cur.fetchall()
        if not rows:
            return "No relevant schema entries found."
        return "\n".join(
            f"- {table}.{column if column else ''} (relevance {sim:.2f}): {description}"
            for table, column, description, sim in rows
        )
    finally:
        conn.close()