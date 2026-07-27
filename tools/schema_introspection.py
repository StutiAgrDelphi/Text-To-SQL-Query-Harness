from typing import Annotated
from pydantic import Field
from agent_framework import tool
from db import get_connection


@tool(approval_mode="never_require")
def list_tables() -> str:
    """List all table names available in the restaurant DB (public schema)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            rows = cur.fetchall()
        return "\n".join(r[0] for r in rows)
    finally:
        conn.close()


@tool(approval_mode="never_require")
def get_table_schema(
    table_name: Annotated[str, Field(description="Exact table name to inspect, as returned by list_tables or search_schema.")],
) -> str:
    """Return the exact column names and data types for a given table. Call this
    after search_schema has narrowed down which table(s) are relevant, to get the
    precise, full column list before writing SQL — never guess a column name."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            rows = cur.fetchall()
        if not rows:
            return f"No table named '{table_name}' found."
        return "\n".join(f"{col} ({dtype})" for col, dtype in rows)
    finally:
        conn.close()