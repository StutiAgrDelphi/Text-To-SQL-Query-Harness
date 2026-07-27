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
    "revenue": "orders.net_sales — dollar amount after discounts. By default, exclude orders where status is 'cancelled' or 'refunded' unless the user explicitly asks to include them.",
    "sales": "Same as revenue: orders.net_sales, excluding cancelled/refunded orders by default.",
    "earnings": "Same as revenue: orders.net_sales, excluding cancelled/refunded orders by default.",
    "amount spent": "Same as revenue: orders.net_sales, excluding cancelled/refunded orders by default.",
    "cash in": "Same as revenue: orders.net_sales, excluding cancelled/refunded orders by default.",
    "customer": "customers table — one row per customer, with loyalty_tier and status.",
    "client": "Same as customer: the customers table.",
    "order": "orders table — one row per order placed, linked to customer and restaurant.",
    "location": "restaurants table — one row per physical restaurant location.",
    "branch": "Same as location: the restaurants table.",
    "outlet": "Same as location: the restaurants table.",
    "dish": "menu_items table — one row per item on the menu, shared across all locations.",
    "product": "Same as dish: the menu_items table.",
    "brand": "restaurants.brand — the parent chain a location belongs to. Multiple locations share a brand.",
    "chain": "Same as brand: restaurants.brand.",
    "loyalty status": "customers.loyalty_tier — bronze, silver, gold, or platinum.",
    "membership tier": "Same as loyalty status: customers.loyalty_tier.",
    "payment type": "orders.payment_method — credit_card, debit_card, apple_pay, or cash.",
    "fulfillment method": "orders.order_channel — dine-in, delivery, or takeout.",
    "channel": "Same as fulfillment method: orders.order_channel.",
}

# --------------------------------------------------------------------------
# STAGE 6 — named metrics: full canonical SQL expressions, so the model
# doesn't invent its own aggregate logic for well-known business metrics.
# --------------------------------------------------------------------------
METRICS = {
    "AOV": (
        "Average Order Value. SQL: SELECT AVG(net_sales) FROM orders WHERE status = 'completed'. "
        "Apply any brand/date/location filters as additional WHERE conditions on the same query."
    ),
    "average order value": "Same as AOV — see AOV definition.",
    "repeat customer": (
        "A customer with more than one completed order. SQL pattern: "
        "SELECT customer_id FROM orders WHERE status = 'completed' "
        "GROUP BY customer_id HAVING COUNT(*) > 1."
    ),
    "churn": (
        "Caveat: this schema has no time-based cohort data, only a static customers.status flag. "
        "The closest available proxy is: SELECT COUNT(*) FILTER (WHERE status = 'inactive') * 1.0 / COUNT(*) "
        "FROM customers. Tell the user this is a snapshot ratio, not a true churn rate over time."
    ),
    "churn rate": "Same as churn — see churn definition and caveat.",
    "best seller": (
        "Menu item with the highest total quantity sold. SQL: "
        "SELECT m.item_name, SUM(oi.quantity) AS total_qty FROM order_items oi "
        "JOIN orders o ON oi.order_id = o.order_id JOIN menu_items m ON oi.item_id = m.item_id "
        "WHERE o.status = 'completed' GROUP BY m.item_name ORDER BY total_qty DESC LIMIT 1. "
        "Adjust LIMIT for 'top N best sellers' phrasing."
    ),
    "top seller": "Same as best seller — see best seller definition.",
    "peak hours": (
        "Order volume by hour of day. SQL: SELECT EXTRACT(HOUR FROM order_date) AS hr, COUNT(*) "
        "FROM orders WHERE status = 'completed' GROUP BY hr ORDER BY COUNT(*) DESC."
    ),
    "top customers": (
        "Customers ranked by total revenue. SQL: SELECT c.customer_id, c.full_name, SUM(o.net_sales) AS total "
        "FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'completed' "
        "GROUP BY c.customer_id, c.full_name ORDER BY total DESC. Default to LIMIT 10 unless the user specifies N."
    ),
    "discount rate": (
        "Proportion of gross sales given away as discounts. SQL: "
        "SELECT SUM(discount_amount) / SUM(quantity * unit_price) FROM order_items."
    ),
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
                embedding vector(1536),
                UNIQUE (entry_type, normalized_term)
            );
        """)
        cur.execute("TRUNCATE glossary_catalog;")

        for entry_type, source in (("term", TERMS), ("metric", METRICS)):
            for term, definition in source.items():
                vec = embed(f"{term}: {definition}")
                cur.execute(
                    "INSERT INTO glossary_catalog (entry_type, term, normalized_term, definition, embedding) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (entry_type, term, normalize(term), definition, vec),
                )
        conn.commit()
    print(f"Indexed {len(TERMS)} terms and {len(METRICS)} metrics.")


if __name__ == "__main__":
    main()