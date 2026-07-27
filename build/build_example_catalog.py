import os
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

EXAMPLES = [
    (
        "How many active customers do we have?",
        "SELECT COUNT(*) FROM customers WHERE status = 'active';",
    ),
    (
        "What's the average order value for SmashCraft Burgers?",
        # demonstrates: entity resolution (brand) + glossary metric (AOV) composed together
        "SELECT AVG(o.net_sales) FROM orders o "
        "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
        "WHERE r.brand = 'SmashCraft Burgers' AND o.status = 'completed';",
    ),
    (
        "Show me the top 5 best selling menu items last month.",
        # demonstrates: join across order_items/orders/menu_items + date filter + LIMIT
        "SELECT m.item_name, SUM(oi.quantity) AS total_qty "
        "FROM order_items oi "
        "JOIN orders o ON oi.order_id = o.order_id "
        "JOIN menu_items m ON oi.item_id = m.item_id "
        "WHERE o.status = 'completed' "
        "AND o.order_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') "
        "AND o.order_date < date_trunc('month', CURRENT_DATE) "
        "GROUP BY m.item_name ORDER BY total_qty DESC LIMIT 5;",
    ),
    (
        "Which restaurants are currently closed?",
        "SELECT restaurant_name, city, state FROM restaurants WHERE status = 'closed';",
    ),
    (
        "How many orders were placed via delivery in San Francisco?",
        "SELECT COUNT(*) FROM orders o "
        "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
        "WHERE r.city = 'San Francisco' AND o.order_channel = 'delivery';",
    ),
    (
        "List the top 10 customers by total spend.",
        "SELECT c.full_name, SUM(o.net_sales) AS total_spend "
        "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
        "WHERE o.status = 'completed' "
        "GROUP BY c.full_name ORDER BY total_spend DESC LIMIT 10;",
    ),
    (
        "What percentage of orders get discounted?",
        "SELECT 100.0 * COUNT(DISTINCT order_id) FILTER (WHERE discount_amount > 0) "
        "/ COUNT(DISTINCT order_id) FROM order_items;",
    ),
    (
        "How many menu items are unavailable right now?",
        "SELECT COUNT(*) FROM menu_items WHERE is_available = FALSE;",
    ),
]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS example_sql_catalog (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                sql TEXT NOT NULL,
                embedding vector(1536)
            );
        """)
        cur.execute("TRUNCATE example_sql_catalog;")
        for question, sql in EXAMPLES:
            vec = embed(question)
            cur.execute(
                "INSERT INTO example_sql_catalog (question, sql, embedding) VALUES (%s, %s, %s)",
                (question, sql, vec),
            )
        conn.commit()
    print(f"Indexed {len(EXAMPLES)} example SQL pairs.")


if __name__ == "__main__":
    main()