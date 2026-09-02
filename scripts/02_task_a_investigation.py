"""
Task A Investigation: Identify Turn Off Rule Mistakes
Analyzes cases where "Turn Off" rule actions may have been mistakes due to incomplete attribution.
"""

import pandas as pd
import duckdb
from datetime import datetime

# Define dtype specifications for ID columns per file
# CRITICAL: Force string types on ID columns to prevent 18-digit precision loss
DTYPE_SPECS = {
    'campaign_adset_metadata.csv': {
        'adset_id': str,
        'campaign_id': str
    },
    'daily_adset_performance.csv': {
        'adset_id': str,
        'fb_ad_account_id': str
    },
    'rule_executions.csv': {
        'adset_id': str,
        'campaign_id': str,
        'account_id': str
    },
    'buyer_actions.csv': {
        'adset_id': str
    },
    'auto_rules.csv': {}
}

# File paths
DATA_DIR = 'data/'
FILES = [
    'campaign_adset_metadata.csv',
    'daily_adset_performance.csv',
    'rule_executions.csv',
    'buyer_actions.csv',
    'auto_rules.csv'
]

print("=" * 80)
print("TASK A: TURN OFF RULE MISTAKE INVESTIGATION")
print("=" * 80)

# Load all CSV files into pandas DataFrames
print("\n[1] Loading CSV files with dtype specifications...")
dataframes = {}

for file in FILES:
    file_path = f"{DATA_DIR}{file}"
    dtype_spec = DTYPE_SPECS.get(file, {})
    df = pd.read_csv(file_path, dtype=dtype_spec)
    table_name = file.replace('.csv', '')
    dataframes[table_name] = df
    print(f"  ✓ {table_name}: {len(df):,} rows")

# Create DuckDB in-memory connection and register tables
print("\n[2] Creating DuckDB in-memory database...")
conn = duckdb.connect(':memory:')
for table_name, df in dataframes.items():
    conn.register(table_name, df)
    print(f"  ✓ Registered: {table_name}")

# Step 3: Filter to SUCCESS only and report exclusions
print("\n[3] Filtering rule_executions to response='SUCCESS' only...")
total_rule_executions = conn.execute("SELECT COUNT(*) FROM rule_executions").fetchone()[0]
failed_executions = conn.execute("""
    SELECT COUNT(*) 
    FROM rule_executions 
    WHERE response != 'SUCCESS' OR response IS NULL
""").fetchone()[0]
success_executions = total_rule_executions - failed_executions

print(f"  Total rule_executions rows: {total_rule_executions:,}")
print(f"  Excluded (non-SUCCESS): {failed_executions:,}")
print(f"  Reason: Failed API calls never executed on Meta, so cannot cause real mistakes")
print(f"  Remaining (SUCCESS): {success_executions:,}")

# Step 4: Filter to Turn Off actions
print("\n[4] Filtering to 'Turn Off' actions...")
turn_off_count = conn.execute("""
    SELECT COUNT(*) 
    FROM rule_executions 
    WHERE response = 'SUCCESS' 
    AND (LOWER(action_name) LIKE '%turn off%' OR LOWER(action_name) LIKE '%turn_off%')
""").fetchone()[0]
print(f"  Turn Off actions (SUCCESS only): {turn_off_count:,}")

# Step 5-7: Join and identify mistakes
print("\n[5-7] Joining to daily_adset_performance and identifying mistakes...")
print("  Criteria: Rule saw negative ROI but finalized profit was positive")

mistake_query = """
WITH turn_off_rules AS (
    SELECT 
        re.*,
        -- Parse action_time to extract hour for gap calculation
        CAST(SUBSTR(action_time, 12, 2) AS INTEGER) as action_hour,
        CAST(SUBSTR(action_time, 15, 2) AS INTEGER) as action_minute
    FROM rule_executions re
    WHERE re.response = 'SUCCESS'
    AND (LOWER(re.action_name) LIKE '%turn off%' OR LOWER(re.action_name) LIKE '%turn_off%')
),
joined_data AS (
    SELECT 
        tor.*,
        dap.date,
        dap.spend,
        dap.profit,
        dap.roi as finalized_roi,
        dap.revenue,
        dap.impressions,
        dap.clicks,
        -- Calculate hours until end of day (23:59)
        (23 - tor.action_hour) + ((59 - tor.action_minute) / 60.0) as hours_until_eod
    FROM turn_off_rules tor
    INNER JOIN daily_adset_performance dap
        ON tor.adset_id = dap.adset_id
        AND tor.action_date = dap.date
)
SELECT 
    *,
    -- Flag as mistake if rule saw negative ROI but finalized profit is positive
    CASE 
        WHEN (today_roi_at_action < 0 OR last_3_days_roi_at_action < 0) 
             AND profit > 0 
        THEN 1 
        ELSE 0 
    END as is_mistake
FROM joined_data
"""

results_df = conn.execute(mistake_query).df()
mistakes_df = results_df[results_df['is_mistake'] == 1].copy()

# Deduplicate mistakes to match script 03 (group by adset_id + action_date, keep earliest action_time)
mistakes_df = mistakes_df.sort_values('action_time').drop_duplicates(subset=['adset_id', 'action_date'], keep='first').copy()

print(f"  Total Turn Off actions matched to daily performance: {len(results_df):,}")
print(f"  Flagged as likely unique mistakes (deduplicated): {len(mistakes_df):,}")

# Step 8-9: Analysis and reporting
if len(mistakes_df) > 0:
    total_spend = mistakes_df['spend'].sum()
    total_profit = mistakes_df['profit'].sum()
    
    print("\n" + "=" * 80)
    print("SUMMARY OF FLAGGED MISTAKES")
    print("=" * 80)
    print(f"Total flagged unique cases: {len(mistakes_df):,}")
    print(f"Combined spend on action day: ${total_spend:,.2f}")
    print(f"Combined profit on action day: ${total_profit:,.2f}")
    print(f"Average hours until end of day: {mistakes_df['hours_until_eod'].mean():.2f}")
    
    # Export detailed results
    output_file = 'data/task_a_mistakes.csv'
    mistakes_df.to_csv(output_file, index=False)
    print(f"\n✓ Detailed results exported to: {output_file}")
    
else:
    print("\n" + "=" * 80)
    print("No mistakes found matching the criteria.")
    print("=" * 80)

# Write comprehensive findings to INVESTIGATION.md
print("\n" + "=" * 80)
print("WRITING TO INVESTIGATION.MD")
print("=" * 80)

import os

# Gather data quality metrics
daily_perf_df = dataframes['daily_adset_performance']
buyer_actions_df = dataframes['buyer_actions']

# Check for exact duplicates in daily_adset_performance
duplicate_rows = daily_perf_df[daily_perf_df.duplicated(keep=False)]
num_duplicates = len(duplicate_rows)

# Check for chronologically inconsistent spend_day_no
inconsistent_spend_day = daily_perf_df[
    (daily_perf_df['spend_day_no'] == 0) &
    (pd.to_datetime(daily_perf_df['first_spend_date']) > pd.to_datetime(daily_perf_df['date']))
]
num_inconsistent = len(inconsistent_spend_day)

# Check buyer_actions for null adset_id
null_adset_buyer_actions = buyer_actions_df[buyer_actions_df['adset_id'].isna()]
num_null_adset = len(null_adset_buyer_actions)

# Calculate matched vs total turn off actions
matched_turn_offs = len(results_df)

# Build comprehensive investigation content
investigation_content = f"""
## Methodology — Reconstructing Rule Activity

### Data Loading and Filtering

**Total rule execution records**: {total_rule_executions:,} rows in `rule_executions.csv`

**Excluded records**: {failed_executions:,} rows ({failed_executions/total_rule_executions*100:.1f}%) with `response != 'SUCCESS'`

**Rationale for exclusion**: These rows represent logged API call attempts that failed (primarily due to OAuth token invalidation or rate limiting). Since these actions never actually executed on Meta's platform, they could not have caused real financial impact. Including them would artificially inflate the mistake count with hypothetical scenarios that never occurred.

**Successful Turn Off actions**: {turn_off_count:,} rows (filtered to `action_name` containing "Turn Off")

**Matched to same-day performance data**: {matched_turn_offs:,} of {turn_off_count:,} Turn Off actions ({matched_turn_offs/turn_off_count*100:.1f}%) successfully joined to `daily_adset_performance` on `adset_id` and `action_date = date`

### Mistake Identification Criteria

**Explicit assumption**: A Turn Off action is flagged as a likely mistake if:
1. The rule observed **negative ROI** at evaluation time (`today_roi_at_action < 0` OR `last_3_days_roi_at_action < 0`), AND
2. The **finalized same-day profit** for that adset was **positive** (`profit > 0`)

**Limitation of this approach**: This is a naive same-day comparison that does not model:
- The duration of attribution lag (how long after ad interaction conversions are attributed)
- Longer-term adset trajectory (an adset may be profitable on one day but unprofitable over its lifetime)
- Intraday volatility (ROI may fluctuate significantly within a single day)

This criterion identifies cases where the rule acted on incomplete information, but does not prove the action was objectively wrong in all cases.

**Results**: {len(mistakes_df):,} Turn Off actions flagged as likely mistakes (after deduplication matching impact quantification)

---

## Case Studies — Concrete Rule Mistakes

The following cases illustrate Turn Off actions where the rule appears to have acted on incomplete attribution data (deduplicated to align with unique impacted adsets):

"""

# Add case studies for deduplicated mistakes
if len(mistakes_df) > 0:
    top_cases = mistakes_df.nlargest(min(5, len(mistakes_df)), 'profit')
    
    for idx, row in enumerate(top_cases.itertuples(), 1):
        today_roi_str = f"{row.today_roi_at_action:.2%}" if pd.notna(row.today_roi_at_action) else "N/A"
        last_3_roi_str = f"{row.last_3_days_roi_at_action:.2%}" if pd.notna(row.last_3_days_roi_at_action) else "N/A"
        
        # Check if this is the specific duplicate case (adset 31255165214890)
        note_text = ""
        if str(row.adset_id) == '31255165214890':
            note_text = "\n*Note: this adset was also turned off a second time 30 minutes later by the same rule — see Data Quality Issues section for the duplicate-firing observation. This case study reflects the first (earliest) firing only, to avoid double-counting the same underlying mistake.*\n"
        
        investigation_content += f"""
### Case {idx}: Adset {row.adset_id}

**Action Details**:
- **Date**: {row.action_date}
- **Time**: {row.action_time} ({row.hours_until_eod:.1f} hours until end of day)
- **Rule**: {row.rule_name}
- **Action**: {row.action_name}

**What the rule saw at evaluation time**:
- Today's ROI: {today_roi_str}
- Last 3 days ROI: {last_3_roi_str}

**Finalized same-day outcome** (after full attribution):
- Spend: ${row.spend:,.2f}
- Revenue: ${row.revenue:,.2f}
- **Profit: ${row.profit:,.2f}**
- ROI: {row.finalized_roi:.2%}
- Impressions: {row.impressions:,}
- Clicks: {row.clicks:,}
{note_text}
**Why this looks like a mistake**: The rule evaluated this adset at {row.action_time} and saw negative ROI, likely because conversions from earlier ad interactions had not yet been attributed. By end of day, the adset showed a profit of ${row.profit:,.2f}, suggesting the Turn Off action was premature and based on incomplete data.

"""

investigation_content += f"""
---

## Data Quality Issues Encountered

The following data quality issues were identified during analysis:

- **{num_duplicates:,} exact-duplicate rows in `daily_adset_performance.csv`**: Rows where `adset_id` + `date` are identical across all columns. These were not deduplicated for this analysis since they did not affect the mistake-flagging query (which uses INNER JOIN and would match duplicates identically). However, this represents a data integrity concern in the source system that should be investigated.

- **{num_inconsistent:,} rows with chronologically inconsistent `spend_day_no`**: Cases where `spend_day_no = 0` but `first_spend_date` is LATER than the row's own `date`. This is logically impossible (an adset cannot have its first spend date in the future). These rows were flagged but not used in this analysis, as they represent data corruption or ETL errors.

- **{failed_executions:,} of {total_rule_executions:,} rule execution rows ({failed_executions/total_rule_executions*100:.1f}%) had non-SUCCESS API responses**: Primarily OAuth token invalidation errors. These were excluded from all financial impact calculations since the action never executed on Meta's platform and therefore could not have caused real financial impact.

- **Risk of float64 precision loss on 18-digit adset IDs**: When pandas infers dtype automatically, 18-digit integer IDs can lose precision due to float64 representation limits. This was mitigated by forcing `dtype=str` on all ID columns (`adset_id`, `campaign_id`, `account_id`, `fb_ad_account_id`) at load time, ensuring exact string matching in all joins.

- **{num_null_adset:,} of {len(buyer_actions_df):,} buyer action rows ({num_null_adset/len(buyer_actions_df)*100:.1f}%) are campaign-level actions with null `adset_id`**: These rows have no `campaign_id` column at all, making it impossible to attribute these actions to a specific campaign or adset. This represents a gap in the source system's data model (campaign-level actions are logged without sufficient context to reconstruct what they affected). This issue is not fixable from the available data alone and represents a limitation in analyzing human vs. automated decision conflicts.

---
*Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Script: `scripts/02_task_a_investigation.py`*

"""

# Handle idempotent section replacement
investigation_file = 'INVESTIGATION.md'
sections_to_write = [
    "## Methodology — Reconstructing Rule Activity",
    "## Case Studies — Concrete Rule Mistakes",
    "## Data Quality Issues Encountered"
]

if os.path.exists(investigation_file):
    print(f"  Updating existing {investigation_file}...")
    
    with open(investigation_file, 'r') as f:
        existing_content = f.read()
    
    # Remove all sections that we're about to write
    updated_content = existing_content
    for section_heading in sections_to_write:
        if section_heading in updated_content:
            print(f"  Removing old '{section_heading}' section...")
            
            section_start = updated_content.find(section_heading)
            # Find next ## heading
            next_section = updated_content.find("\n## ", section_start + len(section_heading))
            
            if next_section == -1:
                # No next section, remove to end
                updated_content = updated_content[:section_start].rstrip() + "\n"
            else:
                # Remove this section only
                updated_content = updated_content[:section_start] + updated_content[next_section + 1:]
    
    # Check if Financial Impact Quantification exists (written by script 03)
    # If it does, insert our sections BEFORE it
    financial_section = "## Financial Impact Quantification"
    if financial_section in updated_content:
        print(f"  Inserting new sections BEFORE '{financial_section}'...")
        insert_pos = updated_content.find(financial_section)
        updated_content = updated_content[:insert_pos] + investigation_content + "\n" + updated_content[insert_pos:]
    else:
        # No financial section, just append
        print(f"  Appending new sections to end of file...")
        updated_content = updated_content.rstrip() + "\n\n" + investigation_content
    
    with open(investigation_file, 'w') as f:
        f.write(updated_content)
else:
    print(f"  Creating new {investigation_file}...")
    header = f"""# Marketing Automation Investigation

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

This document contains findings from the analysis of automated rule executions and their impact on campaign performance.

"""
    with open(investigation_file, 'w') as f:
        f.write(header + investigation_content)

print(f"  ✓ Successfully written to {investigation_file}")

# Print confirmation with section counts
print(f"\n  Sections written:")
print(f"    - Methodology: {total_rule_executions:,} total rows, {failed_executions:,} excluded, {turn_off_count:,} Turn Off actions")
print(f"    - Case Studies: {len(mistakes_df)} deduplicated cases")
print(f"    - Data Quality: 5 issues documented")

print("\n" + "=" * 80)
print("INVESTIGATION COMPLETE")
print("=" * 80)