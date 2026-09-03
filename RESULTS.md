# POC Results: Adset Decision Agent

## 1. Execution Summary

The Proof of Concept (POC) for the LLM-powered marketing analyst agent successfully completed a full-pass analysis across all 2,064 active adset-date combinations for the trailing 3-day period (2026-06-10 to 2026-06-12).

* **Total Combinations Evaluated:** 2,064
* **Checkpointed Combinations Resumed:** 589
* **Combinations Processed After Resume:** 1,475
* **LLM API Calls Executed in the Final Run:** 510
* **Total API Cost (This Run):** $1.2906
* **Cumulative API Cost (Across All Runs):** ~$1.90 (19% of the $10.00 Task C Budget)

> **Note on Resilience:** The initial execution was unexpectedly interrupted when the local machine shut down. After restarting the pipeline, the checkpoint mechanism detected 589 previously processed combinations and skipped them. This demonstrated the critical value of robust state-recovery for a pipeline consuming paid external APIs.

## 2. The Hybrid Architecture Advantage

A core engineering decision for this POC was implementing a deterministic SQL-based pre-check before triggering paid LLM analysis.

* **Pre-Check Escalations:** 1,308 cases (63.4%)
* **Cases Entering the LLM Pipeline:** 756 cases (36.6%)

**Key Pre-Check Signals:**

* **Insufficient historical data (< 48h):** 1,077 instances.
* **Recent human/rule conflicts:** 243 distinct instances (230 buyer-conflicts + 18 rule-conflicts).

*Note: 12 cases had both an insufficient-data flag and a conflict flag simultaneously. For this reason, the breakdown sums to 1,320, but the union of unique pre-check escalated cases is exactly 1,308.*

The main pattern is that adsets lacking reliable historical data or exhibiting recent manual volatility were blocked from the LLM. Instead of forcing a paid AI guess, the system escalated them for zero API cost.

## 3. LLM Agent Behavior

For the 756 cases that entered the LLM pipeline, **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) analyzed the trailing performance metrics and business context.

**Decision Breakdown:**

* **Escalate for Human Review:** 712 cases (Average Confidence: 27.5%)
* **Active Interventions:** 44 cases (Average Confidence: 65.0% - 86.1%)

  * Pause: 37
  * Scale Up: 4
  * Keep: 2
  * Scale Down: 1

The agent demonstrated strict self-calibration. When signals were ambiguous due to limited context, it explicitly requested human review with low confidence. Conversely, its active interventions (e.g., `pause`) carried high confidence scores (avg 86.1%).

## 4. Overall Decision Distribution

Across all 2,064 evaluated adset-date combinations:

* **Escalate:** 2,020 (97.9%)
* **Pause:** 37
* **Scale Up:** 4
* **Keep:** 2
* **Scale Down:** 1

The 97.9% overall escalation rate is the system's primary operational limitation. It prioritizes safety over autonomy, establishing a baseline that does no harm but requires contextual upgrades to replace a larger portion of human decisions.

## 5. Cost & Efficiency

* **Total Tokens:** 631,283 (Input: 466,465 | Output: 164,818)
* **Average Cost per API Call:** ~$0.00253
* **Total Cost Incurred:** ~$1.90 across all batches.

## 6. Data-Driven Comparison: Agent vs. Rules vs. Buyers

To evaluate the agent's logic against historical actions, agent decisions (excluding pre-check escalations) were joined against `rule_executions.csv` and `buyer_actions.csv` for the same adset-dates.

**Overlaps Found:**

* Agent vs. Auto-Rules: 10 overlapping decisions.
* Agent vs. Human Buyers: 68 overlapping decisions.

**Finding 1: Agent vs. Auto-Rules (Agreement on Pausing, Disagreement on Scaling)**

When evaluating the 10 rule overlaps, the agent showed strong alignment with the rules on terminal cases. For instance, on 2026-06-12 (Adset `31166928670267`) and 2026-06-10 (Adset `31275731845445`), both the agent and the auto-rules independently concluded that the adset must be paused. The finalized data confirms this alignment: both adsets finished with heavily negative ROIs (-1.0 and -0.95 respectively, with almost zero spend).

However, where rules opted to incrementally decrease budgets based on same-day metrics (e.g., Adset `31191755212537` on 2026-06-11: rule triggered `Budget Decrease | -30 < ROI <= -10`), the agent explicitly chose to `escalate`.

* **Verdict:** The finalized outcome supports the agent's caution. Despite the rule's same-day signal of negative ROI, the finalized profit for that adset on that day was +$36.41 (ROI +52%). Blindly decreasing the budget would have starved a profitable late-converter.

> **Crucial Note (Systemic Rule Failure Link):** This exact same adset (`31191755212537`) also appears in the `INVESTIGATION.md` (Task A) case studies. It was hit by a 'Turn Off' rule on the very next day (2026-06-12) acting on stale ROI data, despite finishing that day profitable as well. The same adset being misjudged by two different static rules on two consecutive days—both reversed by the finalized numbers—strengthens the case that this isn't an isolated glitch, but a systematic flaw in how the rule engine evaluates same-day ROI due to attribution lag.

**Finding 2: Agent vs. Human Buyers (Contextual Disagreement)**

Across the 68 overlaps with human buyers, a clear pattern emerged: humans actively adjusted budgets (`ui_update_budget` on adsets like `31124038476129` and `730110245237439923` on 2026-06-12), while the agent overwhelmingly defaulted to `escalate`.

* **Verdict:** The finalized outcomes support the buyers' actions, as both cited adsets closed highly profitable (+$5.26 / ROI +1.24, and +$0.99 / ROI +1.10 respectively). The discrepancy highlights the agent's current contextual boundary: human buyers look at the entire campaign and account-level goals to confidently scale, whereas this POC agent is restricted to isolated 3-day metrics. Lacking cross-campaign context, the agent correctly identified its own uncertainty and escalated, rather than guessing.

## 7. The Feedback Loop (Continuous Improvement)

To ensure the agent gets better week-over-week without retraining the underlying model, the system requires a data-driven feedback loop based on settled outcomes.

* **Signal Source:** After revenue attribution settles (T+2 days, per the delay pattern found in Task A), we compare each stored agent decision against the finalized outcome for that adset/date.
* **Storage:** A simple `agent_outcomes` table keyed by `(adset_id, decision_date, action)` with columns for `realized_profit_delta` and `was_escalation_correct` (i.e., did an escalated case actually turn out to need human intervention).
* **Mechanism:** We do NOT retrain the model. Instead, we programmatically extract a periodically refreshed set of few-shot examples (drawn from the highest-confidence *correct* and *incorrect* past decisions). These are appended dynamically to the system prompt. Alternatively, deterministic pre-check thresholds (like the 24h conflict window) can be tightened if the outcomes table shows we are escalating too many non-issues.

**Feedback Loop Pseudocode:**

```python
def execute_feedback_loop():
    # 1. Fetch settled outcomes (T-2 days)
    settled_data = fetch_finalized_revenue(days_back=2)
    
    # 2. Grade past agent decisions against absolute truth
    graded_log = evaluate_agent_accuracy(agent_csv_log, settled_data)
    
    # 3. Save to storage for analysis
    save_to_database('agent_outcomes', graded_log)
    
    # 4. Extract top errors and successes for few-shot learning
    false_positives = get_top_errors(graded_log, limit=3)
    true_positives = get_top_successes(graded_log, limit=3)
    
    # 5. Update prompt templates with historical context
    update_fewshot_examples_in_prompt(false_positives, true_positives)
```

## 8. Evaluation Path & Success Metrics

Model confidence is a reflection of prompt alignment, not a guarantee of financial correctness. A strong evaluation metric must account for the revenue arrival delay.

**Proposed Success Metrics:**

**Primary Metric (Directional Profit Consistency):** For decisions with a T+2 finalized outcome, the % of non-escalate agent decisions where the realized profit aligned with the recommended action. (e.g., A pause recommendation is scored "correct" only if the adset's finalized T+2 ROI for that day was negative; a scale_up is correct if profit was positive and improving).

**Secondary Metric (Escalation Precision):** Of the cases the agent escalated, what fraction later turned out (via finalized data) to have been genuinely ambiguous vs. cases where a confident action would have been clearly correct in hindsight. This metric is critical because a system that escalates everything scores well on the primary metric trivially; escalation precision distinguishes genuine calibration from blanket caution.

**Deployment Stages:**

* **Offline Evaluation:** Backtest recommendations against matured T+2 outcomes.
* **Shadow Mode:** Run daily on live data without executing API writes; track agreement with human buyers.
* **Controlled Execution:** Grant API write-access within strict monetary sandboxes.

## 9. Architectural Next Steps

**Expand Context Window:** Provide campaign-level aggregated data alongside adset data to reduce the 97.9% LLM escalation rate.

**Refine the Conflict Window:** The 24-hour lockout for recent human actions is too rigid. Reduce this to a 6-hour window (via the Pre-Check SQL) to allow the agent to manage intra-day volatility without constantly escalating.
