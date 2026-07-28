from tools.schema_search import search_schema
from tools.security import check_access

print(search_schema.func("who ordered the most burgers last month"))
print()
print(check_access.func("SELECT full_name, email FROM customers"))
print(check_access.func("SELECT restaurant_name FROM restaurants"))
print(check_access.func("SELECT * FROM ai.agno_sessions"))