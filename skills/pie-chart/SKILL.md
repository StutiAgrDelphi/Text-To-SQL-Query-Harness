---
name: pie-chart
description: >
  Use this skill when the user asks for a pie chart, donut chart, breakdown,
  share, distribution, or proportion — for example: "what percentage of orders
  are paid by credit card?" or "show the share of sales by category".
---
## When to activate this skill
Use pie chart when:
- The user says "pie chart", "breakdown", "share", "proportion", "percentage of", "distribution"
- The question asks how a total is split across groups
- The parts logically add up to a meaningful whole (100%)
Do NOT use for comparisons where values do not form a whole — use bar-chart instead.
## Output Format
After running SQL and getting real result rows, output ONLY a `json:chart` fenced
code block. No other text inside the block — raw JSON only.
### Schema
```json
{
  "type": "pie",
  "title": "A clear descriptive title",
  "description": "One-line subtitle explaining what is being broken down",
  "data": [
    { "name": "Slice Label", "value": 46776.25, "percentage": 22.7 }
  ]
}
Field Definitions — READ CAREFULLY
"value" → THE RAW NUMBER DIRECTLY FROM THE SQL RESULT. This is the actual sales amount, count, or whatever the SQL returned. It is NEVER a percentage. NEVER divide, NEVER multiply by 100. Copy it exactly as-is from the query result.

"percentage" → A SEPARATE field you compute yourself AFTER you have all the raw values. Formula: round((this_item_value / sum_of_all_values) * 100, 1). This is NOT the same as value. Both must be present.