from tools.validation import validate_sql

print(validate_sql.func("SELECT * FROM customers"))
print(validate_sql.func("SELECT nonexistent_column FROM customers"))
print(validate_sql.func("DELETE FROM customers WHERE customer_id = 1"))
print(validate_sql.func("SELECT * FROM fake_table"))