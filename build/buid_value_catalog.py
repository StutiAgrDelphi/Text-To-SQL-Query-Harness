"""
Builds/refreshes the categorical value catalog used for entity/value grounding.
Run this any time the underlying categorical data changes (new restaurants, new menu items, etc).
"""
import os
import re
import sys
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

# (table, column) pairs worth indexing for entity resolution.
CATALOG_COLUMNS = [
    ("restaurants", "brand"),
    ("restaurants", "restaurant_name"),
    ("restaurants", "city"),
    ("restaurants", "state"),
    ("customers", "city"),
    ("customers", "loyalty_tier"),
    ("customers", "status"),
    ("menu_items", "category"),
    ("menu_items", "item_name"),
    ("orders", "order_channel"),
    ("orders", "payment_method"),
    ("orders", "status"),
]


def normalize(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_catalog(compute_embeddings: bool = False, force: bool = False):
    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for table, column in CATALOG_COLUMNS:
                cur.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL;")
                values = [row[0] for row in cur.fetchall()]
                for value in values:
                    normalized = normalize(str(value))
                    cur.execute(
                        """
                        INSERT INTO value_catalog (table_name, column_name, canonical_value, normalized_value)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (table_name, column_name, canonical_value) DO UPDATE
                        SET normalized_value = EXCLUDED.normalized_value;
                        """,
                        (table, column, str(value), normalized),
                    )
                print(f"Indexed {len(values)} distinct values from {table}.{column}")
        conn.commit()

    if compute_embeddings:
        _compute_embeddings(force=force)


def _compute_embeddings(force: bool = False):
    """Builds the embedding text for each catalog row and writes it to the existing
    `embedding` column only (no schema changes). Bare category-style tokens embed
    poorly ("asian" alone gives weak signal) — this wraps them in a short natural
    phrase, and for menu_items.category pulls a couple of real sample dishes as
    context, since that's the column where the semantic gap actually shows up."""
    embedder = AzureOpenAIEmbedder(
        id=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        api_key=os.environ["AZURE_OPENAI_EMBEDDING_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_EMBEDDING_ENDPOINT"],
        api_version=os.environ["AZURE_OPENAI_EMBEDDING_API_VERSION"],
    )

    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            where = "" if force else "WHERE embedding IS NULL"
            cur.execute(f"SELECT id, table_name, column_name, canonical_value FROM value_catalog {where};")
            rows = cur.fetchall()
            print(f"Computing embeddings for {len(rows)} values (force={force})...")

            for row_id, table, column, canonical_value in rows:
                text = _embedding_text(table, column, canonical_value, cur)
                vector = embedder.get_embedding(text)
                if not vector:
                    print(f"  WARNING: empty embedding for id={row_id} ('{text}') — skipped, check embedder config")
                    continue
                cur.execute("UPDATE value_catalog SET embedding = %s WHERE id = %s;", (vector, row_id))
        conn.commit()
    print("Done.")


def _embedding_text(table: str, column: str, canonical_value: str, cur) -> str:
    """Returns the text that actually gets embedded for a catalog row.
    Falls back to the bare canonical_value for columns that are already
    descriptive on their own (brand names, restaurant names, cities)."""
    if (table, column) == ("menu_items", "category"):
        cur.execute(
            "SELECT item_name FROM menu_items WHERE category = %s LIMIT 5;",
            (canonical_value,),
        )
        samples = [r[0] for r in cur.fetchall()]
        if samples:
            return f"menu category '{canonical_value}', example dishes: {', '.join(samples)}"
        return f"menu category: {canonical_value}"

    label_by_column = {
        "order_channel": "order channel",
        "payment_method": "payment method",
        "status": "status",           # covers orders.status and customers.status
        "loyalty_tier": "customer loyalty tier",
    }
    if column in label_by_column:
        return f"{label_by_column[column]}: {canonical_value}"

    return canonical_value


if __name__ == "__main__":
    build_catalog(
        compute_embeddings="--with-embeddings" in sys.argv,
        force="--force" in sys.argv,
    )
