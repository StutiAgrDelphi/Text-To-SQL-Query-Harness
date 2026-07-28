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

KPIS = [
    # --- Single-table (kept from before) ---
    ("How many active customers do we have?",
     "SELECT COUNT(*) FROM customers WHERE status = 'active';",
     "We have {0} active customers."),
    ("How many total customers do we have?",
     "SELECT COUNT(*) FROM customers;",
     "We have {0} total customers."),
    ("How many restaurant locations do we have?", 
     "SELECT COUNT(*) FROM restaurants WHERE status = 'active';",
     "We have {0} active restaurant locations."),
    ("How many total menu items do we have?", 
     "SELECT COUNT(*) FROM menu_items;",
     "We have {0} menu items across all categories."),
    ("How many customers are in each loyalty tier?", 
     "SELECT loyalty_tier, COUNT(*) FROM customers GROUP BY loyalty_tier ORDER BY COUNT(*) DESC;",
     "Customer counts by loyalty tier:\n{0}"),

    # --- 2-table joins ---
    ("What is our total revenue?", 
     "SELECT ROUND(SUM(net_sales), 2) FROM orders WHERE status = 'completed';",
     "Total revenue across all completed orders is ${0}."),
    ("What is our overall average order value?", 
     "SELECT ROUND(AVG(net_sales), 2) FROM orders WHERE status = 'completed';",
     "The overall average order value is ${0}."),
    ("What is our overall discount rate?", 
     "SELECT ROUND(100.0 * SUM(discount_amount) / SUM(quantity * unit_price), 2) FROM order_items;",
     "The overall discount rate across all order line items is {0}%."),
    ("How many orders came through each channel?", 
     "SELECT order_channel, COUNT(*) FROM orders WHERE status = 'completed' GROUP BY order_channel ORDER BY COUNT(*) DESC;",
     "Order counts by channel:\n{0}"),
    ("How many orders were paid with each payment method?", 
     "SELECT payment_method, COUNT(*) FROM orders WHERE status = 'completed' GROUP BY payment_method ORDER BY COUNT(*) DESC;",
     "Order counts by payment method:\n{0}"),
    ("What is our average items per order?", 
     "SELECT ROUND(AVG(item_count), 2) FROM (SELECT order_id, COUNT(*) AS item_count FROM order_items GROUP BY order_id) sub;",
     "The average number of items per order is {0}."),

    # --- orders + restaurants (brand/location level) ---
    ("What is our revenue by brand?", 
     "SELECT r.brand, ROUND(SUM(o.net_sales), 2) AS revenue FROM orders o "
     "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
     "WHERE o.status = 'completed' GROUP BY r.brand ORDER BY revenue DESC;",
     "Revenue by brand (completed orders):\n{0}"),
    ("What is the average order value by brand?", 
     "SELECT r.brand, ROUND(AVG(o.net_sales), 2) AS aov FROM orders o "
     "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
     "WHERE o.status = 'completed' GROUP BY r.brand ORDER BY aov DESC;",
     "Average order value by brand:\n{0}"),
    ("What is our revenue by city?", 
     "SELECT r.city, ROUND(SUM(o.net_sales), 2) AS revenue FROM orders o "
     "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
     "WHERE o.status = 'completed' GROUP BY r.city ORDER BY revenue DESC;",
     "Revenue by city:\n{0}"),
    ("Which restaurant location has the highest revenue?", 
     "SELECT r.restaurant_name, ROUND(SUM(o.net_sales), 2) AS revenue FROM orders o "
     "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
     "WHERE o.status = 'completed' GROUP BY r.restaurant_name ORDER BY revenue DESC LIMIT 1;",
     "The highest-revenue location is {0}, with ${1} in completed order revenue."),
    ("How many orders does each brand get by channel?", 
     "SELECT r.brand, o.order_channel, COUNT(*) FROM orders o "
     "JOIN restaurants r ON o.restaurant_id = r.restaurant_id "
     "WHERE o.status = 'completed' GROUP BY r.brand, o.order_channel ORDER BY r.brand, COUNT(*) DESC;",
     "Order counts by brand and channel:\n{0}"),

    # --- order_items + menu_items (product level) ---
    ("What is our best selling menu item overall?", 
     "SELECT m.item_name, SUM(oi.quantity) AS qty FROM order_items oi "
     "JOIN orders o ON oi.order_id = o.order_id JOIN menu_items m ON oi.item_id = m.item_id "
     "WHERE o.status = 'completed' GROUP BY m.item_name ORDER BY qty DESC LIMIT 1;",
     "The best-selling menu item overall is {0} with {1} units sold."),
    ("What is our most popular menu category?", 
     "SELECT m.category, SUM(oi.quantity) AS qty FROM order_items oi "
     "JOIN orders o ON oi.order_id = o.order_id JOIN menu_items m ON oi.item_id = m.item_id "
     "WHERE o.status = 'completed' GROUP BY m.category ORDER BY qty DESC LIMIT 1;",
     "The most popular menu category is {0}, with {1} units sold."),
    ("What is our revenue by menu category?", 
     "SELECT m.category, ROUND(SUM(oi.quantity * oi.unit_price - oi.discount_amount), 2) AS revenue "
     "FROM order_items oi JOIN orders o ON oi.order_id = o.order_id JOIN menu_items m ON oi.item_id = m.item_id "
     "WHERE o.status = 'completed' GROUP BY m.category ORDER BY revenue DESC;",
     "Revenue by menu category:\n{0}"),

    # --- customers + orders (behavioral) ---
    ("What is the average order value by loyalty tier?", 
     "SELECT c.loyalty_tier, ROUND(AVG(o.net_sales), 2) AS aov FROM orders o "
     "JOIN customers c ON o.customer_id = c.customer_id "
     "WHERE o.status = 'completed' GROUP BY c.loyalty_tier ORDER BY aov DESC;",
     "Average order value by loyalty tier:\n{0}"),
    ("What percentage of our customers have placed more than one order?", 
     "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE order_count > 1) / COUNT(*), 2) FROM "
     "(SELECT customer_id, COUNT(*) AS order_count FROM orders WHERE status = 'completed' GROUP BY customer_id) sub;",
     "{0}% of customers who have ordered have placed more than one completed order."),
    ("What is the total revenue by loyalty tier?", 
     "SELECT c.loyalty_tier, ROUND(SUM(o.net_sales), 2) AS revenue FROM orders o "
     "JOIN customers c ON o.customer_id = c.customer_id "
     "WHERE o.status = 'completed' GROUP BY c.loyalty_tier ORDER BY revenue DESC;",
     "Revenue by loyalty tier:\n{0}"),
    ("Who are our top 10 customers by total spend?", 
     "SELECT c.full_name, ROUND(SUM(o.net_sales), 2) AS total FROM customers c "
     "JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'completed' "
     "GROUP BY c.full_name ORDER BY total DESC LIMIT 10;",
     "Top 10 customers by total spend:\n{0}"),
]

def run_and_format(cur, sql: str, template: str) -> str:
    cur.execute(sql)
    rows = cur.fetchall()
    if len(rows) == 1 and len(rows[0]) == 1:
        return template.format(rows[0][0])
    if len(rows) == 1:
        return template.format(*rows[0])
    lines = "\n".join(" | ".join(str(v) for v in r) for r in rows)
    return template.format(lines)


def main():
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kpi_catalog (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                sql_query TEXT NOT NULL,
                answer TEXT NOT NULL,
                embedding vector(1536)
            );
        """)
        cur.execute("TRUNCATE kpi_catalog;")
        for question, sql, template in KPIS:
            answer = run_and_format(cur, sql, template)
            vec = embed(question)
            cur.execute(
                "INSERT INTO kpi_catalog (question, sql_query, answer, embedding) "
                "VALUES (%s, %s, %s, %s)",
                (question, sql, answer, vec),
            )
        conn.commit()
    print(f"Built {len(KPIS)} KPI entries.")


if __name__ == "__main__":
    main()