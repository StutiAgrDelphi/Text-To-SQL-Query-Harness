# build/build_schema_catalog.py
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

# Hand-authored descriptions — this is what replaces "dump the whole schema
# and hope" and is what caused the hallucinated columns in the Agno version.
SCHEMA = {
    # --------------------------
    # restaurants
    # --------------------------
    ("restaurants", None):
        "Individual restaurant locations belonging to different brands. Multiple restaurant locations can share the same brand. Contains location, seating capacity, opening date, and operating status.",

    ("restaurants", "restaurant_id"):
        "Primary key identifying a restaurant location.",

    ("restaurants", "restaurant_name"):
        "Display name of a specific restaurant location, usually in the format 'Brand - Neighborhood'. Use when referring to one specific location, not the entire brand.",

    ("restaurants", "brand"):
        "Parent restaurant brand or chain. Multiple restaurant locations can belong to the same brand. Use this when users ask about a brand or chain rather than a specific location.",

    ("restaurants", "city"):
        "City where the restaurant location operates.",

    ("restaurants", "state"):
        "US state abbreviation for the restaurant location.",

    ("restaurants", "country"):
        "Country where the restaurant operates. Current data contains USA.",

    ("restaurants", "opened_date"):
        "Date the restaurant location opened.",

    ("restaurants", "seating_capacity"):
        "Maximum number of customers that can be seated at the restaurant.",

    ("restaurants", "status"):
        "Restaurant operating status. Active means open and operating. Closed means no longer operating.",

    # --------------------------
    # customers
    # --------------------------
    ("customers", None):
        "Customers who place restaurant orders. Includes customer information, loyalty tier, signup details, and account status.",

    ("customers", "customer_id"):
        "Primary key identifying a customer.",

    ("customers", "full_name"):
        "Customer's full name.",

    ("customers", "email"):
        "Unique email address for the customer.",

    ("customers", "city"):
        "Customer's city of residence. Independent of restaurant location.",

    ("customers", "signup_date"):
        "Date the customer registered.",

    ("customers", "loyalty_tier"):
        "Customer loyalty program tier. Possible values are bronze, silver, gold, and platinum. Higher tiers indicate more loyal customers.",

    ("customers", "status"):
        "Customer account status. Active customers have status='active'.",

    # --------------------------
    # menu_items
    # --------------------------
    ("menu_items", None):
        "Catalog of menu items available for ordering across all restaurant brands. Items are shared across restaurants and are not location-specific.",

    ("menu_items", "item_id"):
        "Primary key identifying a menu item.",

    ("menu_items", "item_name"):
        "Display name of the menu item.",

    ("menu_items", "category"):
        "Menu category such as burger, mexican, pizza, asian, side, beverage, or dessert.",

    ("menu_items", "base_price"):
        "Catalog or list price of the menu item before discounts or historical pricing differences.",

    ("menu_items", "is_available"):
        "Whether the menu item is currently available for ordering.",

    # --------------------------
    # orders
    # --------------------------
    ("orders", None):
        "Customer orders placed at restaurant locations. One row represents one customer order and includes revenue, payment, fulfillment channel, and order status.",

    ("orders", "order_id"):
        "Primary key identifying an order.",

    ("orders", "customer_id"):
        "Foreign key referencing the customer who placed the order.",

    ("orders", "restaurant_id"):
        "Foreign key referencing the restaurant where the order was placed.",

    ("orders", "order_date"):
        "Timestamp when the customer placed the order.",

    ("orders", "order_channel"):
        "How the customer placed or received the order. Possible values include dine-in, delivery, and takeout.",

    ("orders", "payment_method"):
        "Method used to pay for the order, such as credit card, debit card, Apple Pay, or cash.",

    ("orders", "status"):
        "Order outcome. Completed orders represent valid sales. Cancelled or refunded orders are normally excluded from revenue calculations unless explicitly requested.",

    ("orders", "net_sales"):
        "Revenue generated by the order after discounts. This is the correct column for revenue, sales, earnings, amount spent, or total sales questions.",

    # --------------------------
    # order_items
    # --------------------------
    ("order_items", None):
        "Individual line items belonging to customer orders. One row represents one menu item purchased within an order.",

    ("order_items", "order_item_id"):
        "Primary key identifying an order line item.",

    ("order_items", "order_id"):
        "Foreign key referencing the parent order.",

    ("order_items", "item_id"):
        "Foreign key referencing the ordered menu item.",

    ("order_items", "quantity"):
        "Number of units purchased for this menu item within the order.",

    ("order_items", "unit_price"):
        "Actual price charged per unit for this order line. May differ from the catalog base price.",

    ("order_items", "discount_amount"):
        "Flat dollar discount applied to this order line. Not a percentage discount.",
}

def main():
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_catalog (
                id SERIAL PRIMARY KEY,
                table_name TEXT NOT NULL,
                column_name TEXT,
                description TEXT NOT NULL,
                embedding vector(1536)
            );
        """)
        cur.execute("TRUNCATE schema_catalog;")
        for (table, column), description in SCHEMA.items():
            vec = embed(f"{table}{'.' + column if column else ''}: {description}")
            cur.execute(
                "INSERT INTO schema_catalog (table_name, column_name, description, embedding) VALUES (%s,%s,%s,%s)",
                (table, column, description, vec),
            )
        conn.commit()
    print(f"Indexed {len(SCHEMA)} schema entries.")

if __name__ == "__main__":
    main()