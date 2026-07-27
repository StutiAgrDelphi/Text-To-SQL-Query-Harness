import os
import re
import json
from pathlib import Path
from typing import Annotated
from pydantic import Field
from agent_framework import tool
from openai import AzureOpenAI
from db import get_connection

ALIASES_PATH = Path(__file__).parent / "aliases.json"

FUZZY_ACCEPT = 0.6
EMBED_ACCEPT = 0.90

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


def normalize(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def load_aliases() -> dict:
    return json.loads(ALIASES_PATH.read_text()) if ALIASES_PATH.exists() else {}


def lookup_alias(column_name: str, table_name: str | None, normalized: str) -> str | None:
    aliases = load_aliases()
    if table_name:
        scoped = aliases.get(f"{table_name}.{column_name}", {})
        if normalized in scoped:
            return scoped[normalized]
    return aliases.get(column_name, {}).get(normalized)


def embed(text: str):
    resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding


def llm_resolve(column_name: str, value: str, candidates: list[str]) -> str | None:
    """Last-resort tier: ask the model to pick the best candidate, or say NONE.
    Only called with a short, pre-filtered candidate list — never the full column."""
    if not candidates:
        return None
    prompt = (
        f"A user referred to a '{column_name}' value as: '{value}'.\n"
        f"The only valid values in the database are: {candidates}.\n"
        "Which one did they most likely mean? Reply with ONLY the exact value from the "
        "list, or NONE if it's genuinely ambiguous or doesn't match any of them."
    )
    resp = chat_client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    answer = resp.choices[0].message.content.strip()
    return answer if answer in candidates else None


@tool(approval_mode="never_require")
def resolve_entity(
    column_name: Annotated[str, Field(description="Categorical column to resolve against: 'brand', 'city', 'category', 'loyalty_tier', 'order_channel', 'payment_method', or 'status'.")],
    value: Annotated[str, Field(description="The raw value as the user typed or implied it, e.g. '5 Guy'.")],
    table_name: Annotated[str | None, Field(description="Required when column_name is 'status', since customers/restaurants/orders each have a different status column with different valid values. Optional otherwise.")] = None,
) -> str:
    """Resolve a raw user-typed value to the real canonical value(s) in the database.
    Tries exact match, then known alias, then fuzzy string match, then embedding
    similarity, then an LLM tiebreak over the remaining candidates — stopping at the
    first confident hit. ALWAYS call this before filtering on a categorical value.
    ALWAYS pass table_name when column_name is 'status'."""
    normalized = normalize(value)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            table_filter = " AND table_name = %s" if table_name else ""
            params_base = (column_name, table_name) if table_name else (column_name,)

            # 1. Exact
            cur.execute(
                f"SELECT DISTINCT table_name, canonical_value FROM value_catalog "
                f"WHERE column_name = %s{table_filter} AND normalized_value = %s",
                params_base + (normalized,) if table_name else (column_name, normalized),
            )
            rows = cur.fetchall()
            if rows:
                return _format("exact", 1.0, rows)

            # 2. Alias
            alias_target = lookup_alias(column_name, table_name, normalized)
            if alias_target:
                cur.execute(
                    f"SELECT DISTINCT table_name, canonical_value FROM value_catalog "
                    f"WHERE column_name = %s{table_filter} AND canonical_value = %s",
                    params_base + (alias_target,) if table_name else (column_name, alias_target),
                )
                rows = cur.fetchall()
                if rows:
                    return _format("alias", 0.98, rows)

            # 3. Fuzzy (pg_trgm)
            cur.execute(
                f"SELECT table_name, canonical_value, similarity(normalized_value, %s) AS sim "
                f"FROM value_catalog WHERE column_name = %s{table_filter} ORDER BY sim DESC LIMIT 5",
                (normalized,) + params_base if table_name else (normalized, column_name),
            )
            fuzzy_rows = cur.fetchall()
            if fuzzy_rows and fuzzy_rows[0][2] >= FUZZY_ACCEPT:
                t, v, sim = fuzzy_rows[0]
                return _format("fuzzy", sim, [(t, v)])

            # 4. Embedding
            vec = embed(f"{column_name}: {value}")
            cur.execute(
                f"SELECT table_name, canonical_value, 1 - (embedding <=> %s::vector) AS sim "
                f"FROM value_catalog WHERE column_name = %s{table_filter} AND embedding IS NOT NULL "
                f"ORDER BY embedding <=> %s::vector LIMIT 5",
                (vec, column_name) + ((table_name,) if table_name else ()) + (vec,),
            )
            embed_rows = cur.fetchall()
            if embed_rows and embed_rows[0][2] >= EMBED_ACCEPT:
                t, v, sim = embed_rows[0]
                return _format("embedding", sim, [(t, v)])

            # 5. LLM tiebreak over the merged candidate pool from fuzzy + embedding
            candidates = sorted({r[1] for r in fuzzy_rows} | {r[1] for r in embed_rows})
            llm_pick = llm_resolve(column_name, value, candidates)
            if llm_pick:
                rows = [r for r in (fuzzy_rows + embed_rows) if r[1] == llm_pick]
                return _format("llm", 0.75, [(r[0], r[1]) for r in rows])

            # 6. Nothing confident — surface candidates, don't guess
            if candidates:
                return (
                    f"No confident match for '{value}' in {column_name}. "
                    f"Closest candidates: {candidates}. Ask the user which one they meant."
                )
            return f"No match found for '{value}' in {column_name} — this value may not exist."
    finally:
        conn.close()


def _format(method: str, confidence: float, rows) -> str:
    values = sorted({r[1] for r in rows})
    tables = sorted({r[0] for r in rows})
    picked = values[0] if len(values) == 1 else values
    return f"Resolved to '{picked}' via {method} match (confidence {confidence:.2f}) in {tables}."