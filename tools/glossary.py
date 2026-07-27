import os
import re
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

SEMANTIC_ACCEPT = 0.85  # raised — this tier is now only for close paraphrases;
                         # looser matches get routed to the LLM tier instead of guessed
TOP_K = 5


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def embed(text: str):
    resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding


def llm_pick(entry_type: str, phrase: str, candidates: list[tuple[str, str]]) -> str | None:
    """candidates: list of (term, definition). Ask the model which one the phrase
    actually refers to, over a small pre-filtered list — never the full glossary."""
    if not candidates:
        return None
    listing = "\n".join(f"- {term}: {definition}" for term, definition in candidates)
    prompt = (
        f"A user's question used the phrase: '{phrase}'.\n"
        f"Here are the defined {entry_type}s it might refer to:\n{listing}\n\n"
        "Which term (if any) does the phrase clearly refer to? Reply with ONLY the "
        "exact term text from the list above, or NONE if it doesn't clearly match any of them."
    )
    resp = chat_client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    answer = resp.choices[0].message.content.strip()
    matches = [d for t, d in candidates if t == answer]
    return matches[0] if matches else None


def _lookup(entry_type: str, phrase: str) -> str:
    normalized = normalize(phrase)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1. Exact
            cur.execute(
                "SELECT definition FROM glossary_catalog WHERE entry_type = %s AND normalized_term = %s",
                (entry_type, normalized),
            )
            row = cur.fetchone()
            if row:
                return row[0]

            # 2. Embedding — top-k candidates
            vec = embed(phrase)
            cur.execute(
                "SELECT term, definition, 1 - (embedding <=> %s::vector) AS sim "
                "FROM glossary_catalog WHERE entry_type = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, entry_type, vec, TOP_K),
            )
            candidates = cur.fetchall()  # [(term, definition, sim), ...]
            if candidates and candidates[0][2] >= SEMANTIC_ACCEPT:
                return candidates[0][1]

            # 3. LLM tiebreak over the same candidate pool
            pool = [(t, d) for t, d, _ in candidates]
            picked = llm_pick(entry_type, phrase, pool)
            if picked:
                return picked

            # 4. Genuinely undefined — don't guess
            return (
                f"No defined {entry_type} matches '{phrase}'. Don't invent an interpretation — "
                f"use the raw schema/column info instead, or ask the user to clarify."
            )
    finally:
        conn.close()


@tool(approval_mode="never_require")
def lookup_glossary_term(
    phrase: Annotated[str, Field(description="Business language from the user's question that might map to a specific table or column, e.g. 'revenue', 'customer', 'branch'.")],
) -> str:
    """Stage 4 — look up what a business term actually refers to in the database
    (which table/column). ALWAYS call this before assuming what a business word
    like 'revenue', 'customer', or 'branch' maps to — never guess."""
    return _lookup("term", phrase)


@tool(approval_mode="never_require")
def lookup_metric(
    phrase: Annotated[str, Field(description="A named business metric from the user's question, e.g. 'AOV', 'churn rate', 'best seller', 'top customers'.")],
) -> str:
    """Stage 6 — look up the exact, pre-approved SQL definition for a named metric.
    ALWAYS call this before computing a metric like AOV, churn, best seller, or
    top customers yourself — use the returned SQL pattern instead of inventing
    your own aggregate logic."""
    return _lookup("metric", phrase)