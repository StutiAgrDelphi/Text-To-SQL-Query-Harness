from tools.entity_resolution import resolve_entity

tests = [
    ("brand", "5 Guy", None),               # should fail gracefully (not in your data) — sanity check on "no match"
    ("brand", "smash craft", None),         # alias
    ("brand", "smshcraft burgers", None),   # fuzzy (typo)
    ("city", "sf", None),                   # alias
    ("category", "tacos", None),            # alias
    ("status", "shut down", "restaurants"), # alias, table-scoped
    ("status", "active", "customers"),      # exact, table-scoped
    ("status", "active", None),             # ambiguous on purpose — should return both tables
]
for column, val, table in tests:
    print(f"{column}='{val}' (table={table}) -> {resolve_entity.func(column, val, table)}")