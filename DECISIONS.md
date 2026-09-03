# AI Usage & Architecture Decisions Log

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

### 11. Second Model Name Guess Failure
* **Action:** After fixing the first deprecated model, a follow-up attempt to "self-correct" the model string produced ANOTHER wrong guess (`claude-3-haiku-20240307`), also returning a 404, before manually specifying the exact correct string (`claude-haiku-4-5-20251001`).
* **Reasoning:** This showed the AI tool guessing plausible-sounding model names from training data rather than verifying against current docs. This reinforced the need for explicit, manually-confirmed model strings rather than trusting AI-suggested "fixes" to AI-suggested code.

### 12. Checkpoint/Resume Design Over Simple Retry
* **Action:** For the full-pass execution across 2,064 combinations, chose append-per-decision CSV checkpointing with a resume-on-restart mechanism, rather than just wrapping API calls in a retry decorator.
* **Reasoning:** Retries handle transient network errors but not a full local crash. Checkpointing survives worse failure modes without re-paying for already-completed API calls. 
* **Result:** This was validated for real—the local machine shut down mid-run, and on restart the pipeline correctly skipped 589 already-processed combinations, completing the remaining 1,475 without any duplicate spend.

### 13. Escalate-vs-Budget-Exhausted Ordering Bug
* **Action:** Initial full-pass logic checked budget exhaustion before pre-check escalation, causing free escalations (which needed no LLM call) to be incorrectly overwritten with a "budget exhausted" placeholder once the cap was hit.
* **Reasoning:** Reordered so pre-check escalations are always recorded with their real reason regardless of budget state. Only genuine cases that "would have needed an LLM call but couldn't afford it" get the budget-exhausted flag.

### 14. Data-Driven Comparison Instead of Narrative
* **Action:** Built `scripts/05_evaluate_overlaps.py` to join `agent_decisions.csv` against `rule_executions.csv` and `buyer_actions.csv` on real `adset_id` + `date`, rather than writing a general qualitative comparison paragraph.
* **Reasoning:** An early draft of the Task C comparison section made plausible-sounding claims without citing specific cases. Enforcing the actual join surfaced concrete IDs (e.g., `31191755212537`) whose finalized outcomes could be verified against both the rule's and the agent's decisions—including a direct cross-reference to the same adset already documented as a Task A mistake case.