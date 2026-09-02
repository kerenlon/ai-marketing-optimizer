### 1. Environment & AI Tooling Setup
* **Action:** Selected Roo Code (API-based VS Code extension) instead of the standard Claude Code CLI.
* **Reasoning:** Direct pay-as-you-go API billing provides granular per-request cost visibility, which better supports the strict $10 budget-tracking requirement than a flat subscription would.

### 2. Data Ingestion: Preventing ID Corruption
* **Action:** Forced `dtype=str` per-file on exact Meta ID columns (`adset_id`, `campaign_id`, `fb_ad_account_id`, `account_id`) during pandas loading.
* **Reasoning:** Default pandas behavior casts numeric columns with missing values to `float64`. For 18-digit Meta IDs, this causes catastrophic precision loss. Applying a blanket `dtype` mapping would fail silently due to inconsistent column naming across files (e.g., `fb_ad_account_id` vs `account_id`).

### 3. Verified Ingestion
* **Action:** Confirmed all ID columns loaded as `object` (string) dtype, not `float64`, via explicit dtype checks post-load.
* **Result:** Verified row counts across all tables: `campaign_adset_metadata` (7,129 rows), `daily_adset_performance` (4,947 rows), `rule_executions` (214 rows), `buyer_actions` (1,001 rows), and `auto_rules` (12 rows). All ID columns were successfully confirmed as loaded with `dtype=object`.

### 4. Model Deprecation Caught at Runtime
* **Action:** Initial script used `claude-3-5-haiku-20241022`, which returned a 404 (deprecated). Updated to `claude-haiku-4-5-20251001`, current pricing.
* **Reasoning:** AI-generated code referenced a model version that no longer exists — a reminder to verify model availability against live docs rather than trusting a hardcoded string, especially since the space moves fast.

### 5. Robust Handling of LLM Markdown Fences
* **Action:** Added a text-cleaning step before `json.loads` to strip markdown code fences if the model wraps the output despite instructions, appending a `required_markdown_stripping` data quality flag.
* **Reasoning:** Models frequently ignore negative constraints regarding formatting. This ensures parsing resilience while preserving full auditability in the final dataset trail.

### 6. Output Validation and Action Guardrails
* **Action:** Implemented programmatic validation for the LLM's returned `action` and `amount` fields, forcing an `escalate` override with specific flags (`invalid_action` or `missing_amount_for_scale_action`) upon malformed outputs.
* **Reasoning:** A syntactically valid JSON payload can still contain hallucinated enums or missing budgetary figures. Guarding against these edge cases prevents unsafe programmatic budget modifications.

### 7. Preventing Self-Conflict in Pre-Checks
* **Action:** Refined the 24-hour rule/buyer-action conflict filter in `flag_uncertainty` to explicitly exclude actions dated on the decision date itself.
* **Reasoning:** The initial check accidentally flagged a decision as conflicting with itself when evaluating the very action that constituted a Task A mistake case. Restricting the check to strictly prior actions eliminates this false positive.

### 8. Documenting Null-Revenue Limitations
* **Action:** Retained the null-revenue delayed attribution trigger in `flag_uncertainty` while formally documenting that it remains dormant on the current dataset snapshot where revenue is null exclusively when spend equals zero.
* **Reasoning:** While inactive for this specific dataset snapshot, the logic remains architecturally sound and necessary for broader live production data streams.

### 9. Eliminating Hardcoded Metrics in Impact Quantification
* **Action:** Replaced hardcoded sample-size strings (e.g., "3 unique adsets") in `03_impact_quantification.py` with dynamic f-string references to the computed `unique_adsets` variable, implementing idempotent section replacement.
* **Reasoning:** Hardcoded numbers across text blocks create internal document contradictions when underlying datasets shift. Dynamic variable binding combined with idempotent cleanups guarantees data consistency.

### 10. Parameterizing SQL Queries for Injection Defense
* **Action:** Converted f-string query interpolations within `build_context` to parameterized DuckDB queries utilizing `?` placeholders.
* **Reasoning:** Although dataset identifiers are system-generated rather than user-controlled, adopting parameterization universally establishes a defensive coding baseline against injection vulnerabilities.