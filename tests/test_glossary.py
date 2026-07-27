from tools.glossary import lookup_glossary_term, lookup_metric

for phrase in ["revenue", "cash in", "branch", "how much money we make"]:
    print(f"term '{phrase}' -> {lookup_glossary_term.func(phrase)}\n")

for phrase in ["AOV", "average order value", "regulars", "churn", "who buys the most"]:
    print(f"metric '{phrase}' -> {lookup_metric.func(phrase)}\n")