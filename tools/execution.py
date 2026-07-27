from typing import Annotated
from pydantic import Field
from agent_framework import tool
from db import get_connection


@tool(approval_mode="never_require")
def run_sql(
    query: Annotated[str, Field(description="A validated, read-only SELECT query to execute — call this only after check_access and validate_sql have both passed.")],
) -> str:
    if not query.strip().lower().startswith("select"):
        return "Error: only SELECT queries are allowed."
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 5000")
            cur.execute(query)
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]
        return f"{colnames}\n" + "\n".join(str(r) for r in rows[:50])
    except Exception as e:
        return f"SQL error: {e}"
    finally:
        conn.close()