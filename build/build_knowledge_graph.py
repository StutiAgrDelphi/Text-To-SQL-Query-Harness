from mcp.client import session
import os
import re
import psycopg2
from dotenv import load_dotenv
from db_neo4j import get_driver

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

# Hand-curated conceptual relationships — this is the part embeddings can't give you.
RELATED_TERM_PAIRS = [
    ("term:revenue", "metric:AOV"),
    ("term:revenue", "metric:churn"),
    ("term:revenue", "metric:top customers"),
    ("term:revenue", "metric:discount rate"),
    ("metric:AOV", "metric:discount rate"),
    ("metric:repeat customer", "metric:churn"),
    ("metric:best seller", "term:revenue"),
    ("metric:peak hours", "term:order"),
]

def fetch_schema_rows(cur):
    cur.execute("SELECT table_name, column_name, description FROM schema_catalog;")
    return cur.fetchall()

def fetch_foreign_keys(cur):
    cur.execute("""
        SELECT tc.table_name AS child_table, kcu.column_name AS child_column,
               ccu.table_name AS parent_table, ccu.column_name AS parent_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY';
    """)
    return cur.fetchall()

def fetch_glossary_rows(cur):
    cur.execute("""
        SELECT entry_type, term, definition, formula_sql,
               maps_to_table, maps_to_column, synonym_of
        FROM glossary_catalog;
    """)
    return cur.fetchall()

# def parse_maps_to(definition: str):
#     """Best-effort: pull a 'table.column' or 'table table' reference out of the
#     free-text definition, since your TERMS/METRICS dicts were authored in a
#     consistent style. Returns ('column', 'table.col') or ('table', 'table') or None."""
#     m = re.search(r"\b([a-z_]+)\.([a-z_]+)\b", definition)
#     if m:
#         return "column", f"{m.group(1)}.{m.group(2)}"
#     m = re.search(r"\b([a-z_]+) table\b", definition)
#     if m:
#         return "table", m.group(1)
#     return None

def main():
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        schema_rows = fetch_schema_rows(cur)
        fk_rows = fetch_foreign_keys(cur)
        glossary_rows = fetch_glossary_rows(cur)
    conn.close()

    driver = get_driver()
    with driver.session() as session:
        session.run("CREATE CONSTRAINT table_name IF NOT EXISTS FOR (t:Table) REQUIRE t.name IS UNIQUE;")
        session.run("CREATE CONSTRAINT column_key IF NOT EXISTS FOR (c:Column) REQUIRE c.key IS UNIQUE;")
        session.run("CREATE CONSTRAINT glossary_key IF NOT EXISTS FOR (g:GlossaryEntry) REQUIRE g.key IS UNIQUE;")

        # Tables + columns
        for table, column, description in schema_rows:
            if column is None:
                session.run(
                    "MERGE (t:Table {name: $table}) SET t.description = $desc",
                    table=table, desc=description,
                )
            else:
                key = f"{table}.{column}"
                session.run(
                    """
                    MERGE (t:Table {name: $table})
                    MERGE (c:Column {key: $key})
                    SET c.name = $column, c.table = $table, c.description = $desc
                    MERGE (t)-[:HAS_COLUMN]->(c)
                    """,
                    table=table, key=key, column=column, desc=description,
                )
        print(f"Loaded {len(schema_rows)} schema entries.")

        # Foreign keys
        for child_table, child_col, parent_table, parent_col in fk_rows:
            session.run(
                """
                MATCH (c1:Column {key: $ck}), (c2:Column {key: $pk})
                MERGE (c1)-[:REFERENCES]->(c2)
                WITH c1, c2
                MATCH (t1:Table {name: c1.table}), (t2:Table {name: c2.table})
                MERGE (t1)-[:JOINS_TO]->(t2)
                """,
                ck=f"{child_table}.{child_col}", pk=f"{parent_table}.{parent_col}",
            )
        print(f"Loaded {len(fk_rows)} foreign keys.")

        # Glossary terms/metrics + best-effort MAPS_TO
        for entry_type, term, definition, formula_sql, maps_table, maps_col, synonym_of in glossary_rows:
            key = f"{entry_type}:{term}"
            label = "Metric" if entry_type == "metric" else "BusinessTerm"   # real node types
            session.run(
                f"""
                MERGE (g:{label}:GlossaryEntry {{key: $key}})
                SET g.term = $term, g.definition = $definition, g.formula_sql = $formula_sql
                """,
                key=key, term=term, definition=definition, formula_sql=formula_sql,
            )
            if maps_col:
                session.run(
                    "MATCH (g:GlossaryEntry {key:$key}), (c:Column {key:$target}) MERGE (g)-[:MAPS_TO]->(c)",
                    key=key, target=f"{maps_table}.{maps_col}",
                )
            elif maps_table:
                session.run(
                    "MATCH (g:GlossaryEntry {key:$key}), (t:Table {name:$target}) MERGE (g)-[:MAPS_TO]->(t)",
                    key=key, target=maps_table,
                )

        # separate pass for synonyms, now that all entries exist
        for entry_type, term, *_rest, synonym_of in glossary_rows:
            if synonym_of:
                key = f"{entry_type}:{term}"
                session.run(
                    "MATCH (a:GlossaryEntry {key:$a}), (b:GlossaryEntry {key:$b}) "
                    "MERGE (a)-[:SYNONYM_OF]->(b) MERGE (b)-[:SYNONYM_OF]->(a)",
                    a=key, b=synonym_of,
                )

        # Curated relationships
        for a, b in RELATED_TERM_PAIRS:
            session.run(
                """
                MATCH (a:GlossaryEntry {key: $a}), (b:GlossaryEntry {key: $b})
                MERGE (a)-[:RELATED_TO]->(b)
                MERGE (b)-[:RELATED_TO]->(a)
                """,
                a=a, b=b,
            )
        print(f"Loaded {len(RELATED_TERM_PAIRS)} curated relationships.")


        # verify every non-null maps_to actually landed as an edge
        orphans = session.run(
            "MATCH (g:GlossaryEntry) WHERE NOT (g)-[:MAPS_TO]->() AND NOT (g)-[:SYNONYM_OF]->() RETURN g.key AS k"
        ).value("k")
        if orphans:
            print(f"WARNING: these entries have no MAPS_TO or SYNONYM_OF edge: {orphans}")

    driver.close()

if __name__ == "__main__":
    main()