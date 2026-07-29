---
name: bar-chart
description: >
  Use this skill when the user asks for a bar chart, bar graph, column chart,
  or wants to visually compare values across distinct categories such as brands,
  cities, payment methods, order statuses, or time periods.
---

## When to activate this skill

Use bar chart when:
- The user says "bar chart", "bar graph", "column chart", "compare", "ranking"
- The question compares a measure (sales, orders, revenue) across categories
- Categories are discrete (brands, cities, channels, months, tiers)

Do NOT use for proportional breakdowns — use the pie-chart skill for those.

## Output Format

After running SQL and getting real result rows, output ONLY a `json:chart` fenced
code block. No text inside the block — raw JSON only.

### Schema

```json
{
  "type": "bar",
  "title": "A clear descriptive title",
  "description": "One-line subtitle: what measure, what scope, what filter",
  "x_label": "What the categories represent (e.g. Brand, City, Month)",
  "y_label": "What the values represent (e.g. Total Sales in ₹, Order Count)",
  "data": [
    { "name": "Category Label", "value": 12345.67 }
  ]
}
 