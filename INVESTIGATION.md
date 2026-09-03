# Marketing Automation Investigation

*Generated: 2026-09-01 22:41:46*

This document contains findings from the analysis of automated rule executions and their impact on campaign performance.




## Methodology — Reconstructing Rule Activity

### Analysis Scope

**Account coverage**: This analysis covers 1 account(s) from `rule_executions.csv`:
- `9913405683583663`: 214 rule execution rows

**Scope limitation**: This represents 1 out of 6 total ad accounts in the system. Findings may not generalize to other accounts with different campaign structures, budgets, or optimization strategies.

### Data Loading and Filtering

**Total rule execution records**: 214 rows in `rule_executions.csv`

**Excluded records**: 50 rows (23.4%) with `response != 'SUCCESS'`, broken down as:
- 30 true API failures (OAuth token invalidation, rate limiting)
- 20 system no-ops ("No budget to change" — legitimate cases where the rule determined no action was needed)

**Rationale for exclusion**: API failures never executed on Meta's platform and could not have caused real financial impact. System no-ops represent correct rule behavior (no change needed), not mistakes. Including either would artificially inflate or distort the analysis.

**Successful Turn Off actions**: 152 rows (filtered to `action_name` containing "Turn Off")

**Matched to same-day performance data**: 152 of 152 Turn Off actions (100.0%) successfully joined to `daily_adset_performance` on `adset_id` and `action_date = date`

### Overall Rule Impact

To fully address "how much money did rule-driven actions save or burn," we calculated aggregate finalized metrics for ALL 152 successful Turn Off actions (not just the mistakes):

- **Total spend**: $207.65
- **Total revenue**: $104.13
- **Total profit**: $-103.51
- **Overall ROI**: -49.85%

This represents the finalized same-day financial outcome for all adsets that were turned off by rules during the analysis period.

### Mistake Identification Criteria

**Explicit assumption**: A Turn Off action is flagged as a likely mistake if:
1. The rule observed **negative ROI** at evaluation time (`today_roi_at_action < 0` OR `last_3_days_roi_at_action < 0`), AND
2. The **finalized same-day profit** for that adset was **positive** (`profit > 0`)

**Limitation of this approach**: This is a naive same-day comparison that does not model:
- The duration of attribution lag (how long after ad interaction conversions are attributed)
- Longer-term adset trajectory (an adset may be profitable on one day but unprofitable over its lifetime)
- Intraday volatility (ROI may fluctuate significantly within a single day)

This criterion identifies cases where the rule acted on incomplete information, but does not prove the action was objectively wrong in all cases.

**Results**: 4 Turn Off actions flagged as likely mistakes (after deduplication matching impact quantification)

---

## Case Studies — Concrete Rule Mistakes

The following cases illustrate Turn Off actions where the rule appears to have acted on incomplete attribution data (deduplicated to align with unique impacted adsets):


### Case 1: Adset 31255165214890

**Action Details**:
- **Date**: 2026-06-08
- **Time**: 2026-06-07T22:30:07.000Z (1.5 hours until end of day)
- **Rule**: Turn OFF | Total Days = 4 | OWN RSOC
- **Action**: Turn OFF

**What the rule saw at evaluation time**:
- Today's ROI: -87.00%
- Last 3 days ROI: 5.00%

**Finalized same-day outcome** (after full attribution):
- Spend: $9.60
- Revenue: $12.48
- **Profit: $2.88**
- ROI: 29.98%
- Impressions: 68
- Clicks: 2

*Note: this adset was also turned off a second time 30 minutes later by the same rule — see Data Quality Issues section for the duplicate-firing observation. This case study reflects the first (earliest) firing only, to avoid double-counting the same underlying mistake.*

**Why this looks like a mistake**: The rule evaluated this adset at 2026-06-07T22:30:07.000Z and saw negative ROI, likely because conversions from earlier ad interactions had not yet been attributed. By end of day, the adset showed a profit of $2.88, suggesting the Turn Off action was premature and based on incomplete data.


### Case 2: Adset 31191755212537

**Action Details**:
- **Date**: 2026-06-12
- **Time**: 2026-06-11T23:30:08.000Z (0.5 hours until end of day)
- **Rule**: Turn OFF | Total Days >= 5 | OWN RSOC
- **Action**: Turn OFF

**What the rule saw at evaluation time**:
- Today's ROI: -47.00%
- Last 3 days ROI: 5.00%

**Finalized same-day outcome** (after full attribution):
- Spend: $9.45
- Revenue: $12.28
- **Profit: $2.83**
- ROI: 29.96%
- Impressions: 329
- Clicks: 10

**Why this looks like a mistake**: The rule evaluated this adset at 2026-06-11T23:30:08.000Z and saw negative ROI, likely because conversions from earlier ad interactions had not yet been attributed. By end of day, the adset showed a profit of $2.83, suggesting the Turn Off action was premature and based on incomplete data.


---

## Data Quality Issues Encountered

The following data quality issues were identified during analysis:

- **Duplicate rule firing on adset 31255165214890**: This adset was turned off twice within 30 minutes (at 22:30 and 23:00 on 2026-06-07) by the same rule. This suggests a possible idempotency gap where the rule system may not check current adset status before re-firing on its 30-minute schedule. The duplicate was removed in this analysis to avoid double-counting the same underlying mistake.

- **144 exact-duplicate rows in `daily_adset_performance.csv`**: Rows where `adset_id` + `date` are identical across all columns. These were not deduplicated for this analysis since they did not affect the mistake-flagging query (which uses INNER JOIN and would match duplicates identically). However, this represents a data integrity concern in the source system that should be investigated.

- **565 rows with chronologically inconsistent `spend_day_no`**: Cases where `spend_day_no = 0` but `first_spend_date` is LATER than the row's own `date`. This is logically impossible (an adset cannot have its first spend date in the future). These rows were flagged but not used in this analysis, as they represent data corruption or ETL errors.

- **50 of 214 rule execution rows (23.4%) had non-SUCCESS API responses**: Split as 30 true API failures (OAuth token invalidation, rate limiting) and 20 system no-ops ("No budget to change"). API failures were excluded from financial impact calculations since they never executed on Meta. System no-ops represent correct rule behavior (no change needed) and were also excluded.

- **Risk of float64 precision loss on 18-digit adset IDs**: When pandas infers dtype automatically, 18-digit integer IDs can lose precision due to float64 representation limits. This was mitigated by forcing `dtype=str` on all ID columns (`adset_id`, `campaign_id`, `account_id`, `fb_ad_account_id`) at load time, ensuring exact string matching in all joins.

- **286 of 1,001 buyer action rows (28.6%) are campaign-level actions with null `adset_id`**: These rows have no `campaign_id` column at all, making it impossible to attribute these actions to a specific campaign or adset. This represents a gap in the source system's data model (campaign-level actions are logged without sufficient context to reconstruct what they affected). This issue is not fixable from the available data alone and represents a limitation in analyzing human vs. automated decision conflicts.

---
*Analysis Date: 2026-09-02 17:36:24*
*Script: `scripts/02_task_a_investigation.py`*

## Financial Impact Quantification

### Delayed Attribution Finding

Analysis of Turn Off rule executions revealed that **4 cases** (affecting **4 unique adsets**) were likely mistakes caused by incomplete attribution at evaluation time. In these cases:

- The rule observed negative ROI at the time of evaluation
- However, the finalized same-day performance showed positive profit
- This indicates that conversions were still being attributed after the rule fired

**Pattern observed**: Most mistakes occurred late in the day (evening hours), suggesting attribution lag is most severe near end-of-day when conversions are still being attributed to earlier ad interactions.

### Confident Weekly Impact (Deduplicated Data)

Based on the observed week of data:

- **Unique adsets affected**: 4
- **Mistake events**: 4 (after deduplication)
- **Combined daily spend**: $20.47
- **Combined daily profit lost**: $6.09
- **Mistake rate**: 2.63% of successful Turn Off actions
- **Average profit lost per mistake**: $1.52

**This is the only figure we can state with confidence from the available data.**

### Recommendation

The confident weekly loss of $6.09 from 4 preventable mistakes suggests that implementing attribution-aware rule logic (e.g., waiting longer before evaluating same-day performance, or using multi-day trends instead of intraday ROI) could provide measurable value.

---
*Analysis Date: 2026-09-02 17:36:24*
*Data Period: Week of June 6-12, 2026*
*Script: `scripts/03_impact_quantification.py`*
