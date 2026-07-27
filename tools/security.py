import re
from typing import Annotated
from pydantic import Field
from agent_framework import tool

ALLOWED_TABLES = {
    "restaurants", "customers", "menu_items", "orders", "order_items",
    "value_catalog", "schema_catalog", "glossary_catalog",
}

# Columns that must never appear in query output, even though the table is allowed.
BLOCKED_COLUMNS = {
    "customers": {"email"},
}

TABLE_PATTERN = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", re.IGNORECASE)


@tool(approval_mode="never_require")
def check_access(
    query: Annotated[str, Field(description="The SQL SELECT query about to be executed, checked against the table/column allow-list before running.")],
) -> str:
    referenced = {t.split(".")[-1].lower() for t in TABLE_PATTERN.findall(query)}
    disallowed = referenced - ALLOWED_TABLES
    if disallowed:
        return f"BLOCKED: query references disallowed table(s): {sorted(disallowed)}. Do not execute this query."

    flags = [
        f"{table}.{col}"
        for table, cols in BLOCKED_COLUMNS.items()
        if table in referenced
        for col in cols
        if re.search(rf"\b{col}\b", query, re.IGNORECASE)
    ]
    if flags:
        return f"BLOCKED: query selects restricted column(s): {flags}. Aggregate instead of exposing raw values."

    return "OK: all referenced tables and columns are permitted."