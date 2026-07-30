import os
import re
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

embed_client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_EMBEDDING_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_EMBEDDING_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_EMBEDDING_API_VERSION"],
)
EMBED_DEPLOYMENT = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]

def embed(text: str):
    resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding

def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# --------------------------------------------------------------------------
# STAGE 4 — business terms: simple pointers to a column/table, plain-language
# aliases folded in as separate rows so exact-match catches common phrasings.
# --------------------------------------------------------------------------

TERMS = {
    "revenue": {
        "definition": "Dollar amount after discounts. By default, exclude orders where "
                       "status is 'cancelled' or 'refunded' unless the user explicitly asks to include them.",
        "maps_to_table": "orders", "maps_to_column": "net_sales", "synonym_of": None,
    },
    "sales": {
        "definition": "Same concept as revenue.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:revenue",
    },
    "earnings": {
        "definition": "Same concept as revenue.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:revenue",
    },
    "amount spent": {
        "definition": "Same concept as revenue.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:revenue",
    },
    "cash in": {
        "definition": "Same concept as revenue.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:revenue",
    },
    "customer": {
        "definition": "One row per customer, with loyalty_tier and status.",
        "maps_to_table": "customers", "maps_to_column": None, "synonym_of": None,
    },
    "client": {
        "definition": "Same as customer.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:customer",
    },
    "order": {
        "definition": "One row per order placed, linked to customer and restaurant.",
        "maps_to_table": "orders", "maps_to_column": None, "synonym_of": None,
    },
    "location": {
        "definition": "One row per physical restaurant location.",
        "maps_to_table": "restaurants", "maps_to_column": None, "synonym_of": None,
    },
    "branch": {
        "definition": "Same as location.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:location",
    },
    "outlet": {
        "definition": "Same as location.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:location",
    },
    "dish": {
        "definition": "One row per item on the menu, shared across all locations.",
        "maps_to_table": "menu_items", "maps_to_column": None, "synonym_of": None,
    },
    "product": {
        "definition": "Same as dish.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:dish",
    },
    "brand": {
        "definition": "The parent chain a location belongs to. Multiple locations share a brand.",
        "maps_to_table": "restaurants", "maps_to_column": "brand", "synonym_of": None,
    },
    "chain": {
        "definition": "Same as brand.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:brand",
    },
    "loyalty status": {
        "definition": "bronze, silver, gold, or platinum.",
        "maps_to_table": "customers", "maps_to_column": "loyalty_tier", "synonym_of": None,
    },
    "membership tier": {
        "definition": "Same as loyalty status.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:loyalty status",
    },
    "payment type": {
        "definition": "credit_card, debit_card, apple_pay, or cash.",
        "maps_to_table": "orders", "maps_to_column": "payment_method", "synonym_of": None,
    },
    "fulfillment method": {
        "definition": "dine-in, delivery, or takeout.",
        "maps_to_table": "orders", "maps_to_column": "order_channel", "synonym_of": None,
    },
    "channel": {
        "definition": "Same as fulfillment method.",
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "term:fulfillment method",
    },
}

# --------------------------------------------------------------------------
# STAGE 6 — named metrics: full canonical SQL expressions, so the model
# doesn't invent its own aggregate logic for well-known business metrics.
# --------------------------------------------------------------------------

METRICS = {
    "AOV": {
        "definition": "Average Order Value. Apply any brand/date/location filters as additional WHERE conditions.",
        "formula_sql": "SELECT AVG(net_sales) FROM orders WHERE status = 'completed'",
        "maps_to_table": "orders", "maps_to_column": "net_sales", "synonym_of": None,
    },
    "average order value": {
        "definition": "Same as AOV.",
        "formula_sql": None,
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "metric:AOV",
    },
    "repeat customer": {
        "definition": "A customer with more than one completed order.",
        "formula_sql": (
            "SELECT customer_id FROM orders WHERE status = 'completed' "
            "GROUP BY customer_id HAVING COUNT(*) > 1"
        ),
        "maps_to_table": "orders", "maps_to_column": "customer_id", "synonym_of": None,
    },
    "churn": {
        "definition": "Caveat: this schema has no time-based cohort data, only a static customers.status "
                       "flag. This is a snapshot ratio, not a true churn rate over time — tell the user that.",
        "formula_sql": (
            "SELECT COUNT(*) FILTER (WHERE status = 'inactive') * 1.0 / COUNT(*) FROM customers"
        ),
        "maps_to_table": "customers", "maps_to_column": "status", "synonym_of": None,
    },
    "churn rate": {
        "definition": "Same as churn — carries the same time-based-data caveat.",
        "formula_sql": None,
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "metric:churn",
    },
    "best seller": {
        "definition": "Menu item with the highest total quantity sold. Adjust LIMIT for 'top N' phrasing.",
        "formula_sql": (
            "SELECT m.item_name, SUM(oi.quantity) AS total_qty FROM order_items oi "
            "JOIN orders o ON oi.order_id = o.order_id JOIN menu_items m ON oi.item_id = m.item_id "
            "WHERE o.status = 'completed' GROUP BY m.item_name ORDER BY total_qty DESC LIMIT 1"
        ),
        "maps_to_table": "menu_items", "maps_to_column": "item_name", "synonym_of": None,
    },
    "top seller": {
        "definition": "Same as best seller.",
        "formula_sql": None,
        "maps_to_table": None, "maps_to_column": None, "synonym_of": "metric:best seller",
    },
    "peak hours": {
        "definition": "Order volume by hour of day.",
        "formula_sql": (
            "SELECT EXTRACT(HOUR FROM order_date) AS hr, COUNT(*) FROM orders "
            "WHERE status = 'completed' GROUP BY hr ORDER BY COUNT(*) DESC"
        ),
        "maps_to_table": "orders", "maps_to_column": "order_date", "synonym_of": None,
    },
    "top customers": {
        "definition": "Customers ranked by total revenue. Default to LIMIT 10 unless the user specifies N.",
        "formula_sql": (
            "SELECT c.customer_id, c.full_name, SUM(o.net_sales) AS total FROM customers c "
            "JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'completed' "
            "GROUP BY c.customer_id, c.full_name ORDER BY total DESC"
        ),
        # spans customers + orders — no single column is "the" answer, so table only, column None
        "maps_to_table": "customers", "maps_to_column": None, "synonym_of": None,
    },
    "discount rate": {
        "definition": "Proportion of gross sales given away as discounts.",
        "formula_sql": "SELECT SUM(discount_amount) / SUM(quantity * unit_price) FROM order_items",
        # ratio of two columns on the same table — no single column is "the" answer
        "maps_to_table": "order_items", "maps_to_column": None, "synonym_of": None,
    },
}


def main():
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS glossary_catalog (
                id SERIAL PRIMARY KEY,
                entry_type TEXT NOT NULL CHECK (entry_type IN ('term', 'metric')),
                term TEXT NOT NULL,
                normalized_term TEXT NOT NULL,
                definition TEXT NOT NULL,
                formula_sql TEXT,           
                maps_to_table TEXT,           
                maps_to_column TEXT,          
                synonym_of TEXT,
                embedding vector(1536),
                UNIQUE (entry_type, normalized_term)
            );
        """)
        cur.execute("TRUNCATE glossary_catalog;")

        for entry_type, source in (("term", TERMS), ("metric", METRICS)):
            for term, row in source.items():
                vec = embed(f"{term}: {row['definition']}")
                cur.execute(
                    """INSERT INTO glossary_catalog
                    (entry_type, term, normalized_term, definition, formula_sql,
                        maps_to_table, maps_to_column, synonym_of, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (entry_type, term, normalize(term), row["definition"],
                    row.get("formula_sql"), row.get("maps_to_table"),
                    row.get("maps_to_column"), row.get("synonym_of"), vec),
                )
        conn.commit()
    print(f"Indexed {len(TERMS)} terms and {len(METRICS)} metrics.")


if __name__ == "__main__":
    main()