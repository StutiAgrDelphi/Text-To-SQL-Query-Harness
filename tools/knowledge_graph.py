from typing import Annotated
from pydantic import Field
from agent_framework import tool
from db_neo4j import get_driver

@tool(approval_mode="never_require")
def explore_related(
    concept: Annotated[str, Field(description="A table name, 'table.column', or glossary term/metric (e.g. 'revenue', 'AOV') to explore.")],
) -> str:
    """Traverse the knowledge graph to find tables, columns, and glossary
    terms/metrics related to the given concept, with their descriptions.
    Use this for open-ended or comparative questions to discover what else
    is worth checking beyond the literal terms in the question — never for
    simple single-metric lookups."""
    print("explore_related called")
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n)
            WHERE n.name = $c OR n.term = $c OR n.key CONTAINS $c
            OPTIONAL MATCH (n)-[r]-(m)
            RETURN n, type(r) AS rel, m
            LIMIT 25
            """,
            c=concept,
        )
        lines = []
        for record in result:
            n, rel, m = record["n"], record["rel"], record["m"]
            if m is None:
                continue
            m_label = m.get("term") or m.get("name") or m.get("key")
            m_desc = m.get("definition") or m.get("description") or ""
            lines.append(f"{rel} -> {m_label}: {m_desc}")
        if not lines:
            return f"No graph relationships found for '{concept}'."
        return "\n".join(lines)