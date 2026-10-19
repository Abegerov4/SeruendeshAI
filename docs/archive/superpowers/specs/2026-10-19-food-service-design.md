# Confirmed meals, kitchen hours and complete costs

The user approved the first improvement package: correct food classification, affordable dine-in menus, kitchen hours and complete cost. This extends the existing factual evidence contract; it does not claim that every branch or its fees are known.

## Behavior

- A menu price remains the published base price. A hard meal budget is confirmed only from an explicitly complete, current cost statement for the same offering. Unknown mandatory fees are not zero.
- An optional menu `cost` object carries its own existing Evidence fields and `scope: one_offering`, boolean `complete`, `service_percent`, `mandatory_fixed_amount`, `minimum_payable_amount`. Known amounts are finite nonnegative numbers; percentage is at most 100. Partial statements use `complete: false` and null for unknown terms; they may display a verified fee but never produce a confirmed total. A complete statement requires all three numeric terms explicitly covered. They describe one published offering in the menu price's currency. A required choice without a complete price remains unknown. The server calculates max(base * (1 + percent / 100) + fixed, minimum), rounded to two currency decimals, and exposes `total_price`; it never accepts a client-supplied computed total as evidence.
- A missing, stale, conflicting, wrong-branch or incomplete cost statement produces no confirmed total. Existing base prices remain visible with a clear statement that the total is not confirmed.
- Accepted `kitchen_hours` facts are separate from venue opening hours. `kitchen_closes_at` can preserve an explicitly daily closing clock without inventing an opening time; only an unambiguous same-day evening cutoff filters later arrivals. Optional menu `serving_hours` describes that offering's service window using the same source evidence. A known closed kitchen or offering is excluded at estimated arrival, including each route stop; unknown hours remain explicit and are not described as confirmed service availability. A coffee-only request does not require a meal kitchen.
- Exact food classifications use explicit branch rubrics or accepted category reviews. Generic brand names and unrelated-city websites do not prove a classification, menu, closure or price. Preserve distinctions between a canteen, coffee shop and confectionery using the existing format field and taxonomy.
- Source collection prioritizes canteens and affordable complete meals, especially near EXPO. Keep delivery and dine-in distinct, source dates distinct from fetch dates, exact branches, units and raw hashes. No invented data or inferred absence.

## Delivery and constraints

Use the existing linked worktree and branch big-data. Preserve other agents' changes. External LLM/embeddings total cap is USD0.10; this package uses no paid calls. SMTP stays disabled. The immutable master and original IDs remain preserved. Publish sidecars and an offline local index atomically after other active catalog publication completes. Report accepted and held evidence and remaining unknowns; run meaningful backend/frontend/source tests and an independent review; commit and push through the already-authorized big-data branch.

Transit feeds, detailed entrances and dated event enrichment are separate subsequent packages; this approved first package does not invent those data.
