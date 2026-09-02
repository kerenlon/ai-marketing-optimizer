"""
Impact Quantification Script
Deduplicates mistakes, calculates confident weekly impact, and provides caveated projections.
"""

import pandas as pd
from datetime import datetime
import os

print("=" * 80)
print("FINANCIAL IMPACT QUANTIFICATION")
print("=" * 80)

# Load the mistakes data
print("\n[1] Loading task_a_mistakes.csv...")
mistakes_df = pd.read_csv('data/task_a_mistakes.csv')
print(f"  Total rows loaded: {len(mistakes_df)}")

# Deduplication
print("\n[2] Deduplication: Grouping by adset_id and action_date...")
print("  Keeping only the first event (earliest action_time) per adset per day")

initial_count = len(mistakes_df)

# Convert action_time to datetime for proper sorting
mistakes_df['action_time_dt'] = pd.to_datetime(mistakes_df['action_time'])

# Sort by action_time and keep first occurrence per adset_id + action_date
deduplicated_df = mistakes_df.sort_values('action_time_dt').groupby(
    ['adset_id', 'action_date'], as_index=False
).first()

removed_count = initial_count - len(deduplicated_df)
print(f"  Rows before deduplication: {initial_count}")
print(f"  Rows after deduplication: {len(deduplicated_df)}")
print(f"  Rows removed: {removed_count}")

if removed_count > 0:
    print(f"\n  OBSERVATION: {removed_count} duplicate action(s) detected.")
    print("  This suggests a possible system idempotency gap where the rule may not")
    print("  check current adset status before re-firing on its 30-minute schedule.")
    print("  Note: This is an observation based on the data pattern, not a confirmed")
    print("  root cause, as we don't have direct evidence of why it fired multiple times.")

# Compute confident weekly figures
print("\n" + "=" * 80)
print("CONFIDENT WEEKLY FIGURES (Deduplicated Data)")
print("=" * 80)

unique_adsets = deduplicated_df['adset_id'].nunique()
total_spend = deduplicated_df['spend'].sum()
total_profit_lost = deduplicated_df['profit'].sum()
num_mistakes = len(deduplicated_df)

print(f"\nNumber of unique mistaken adsets: {unique_adsets}")
print(f"Number of mistake events (deduplicated): {num_mistakes}")
print(f"Combined daily spend: ${total_spend:,.2f}")
print(f"Combined daily profit lost: ${total_profit_lost:,.2f}")
print(f"\n✓ This is the only figure we can state with confidence from the data.")

# Load rule_executions to calculate mistake rate
print("\n[3] Calculating weekly mistake rate...")
# We need to load rule_executions to get total successful Turn Off actions
rule_exec_df = pd.read_csv('data/rule_executions.csv', dtype={'adset_id': str, 'campaign_id': str, 'account_id': str})

# Filter to SUCCESS Turn Off actions
successful_turn_offs = rule_exec_df[
    (rule_exec_df['response'] == 'SUCCESS') & 
    (rule_exec_df['action_name'].str.contains('Turn Off', case=False, na=False))
]

total_successful_turn_offs = len(successful_turn_offs)
weekly_mistake_rate = (num_mistakes / total_successful_turn_offs) * 100 if total_successful_turn_offs > 0 else 0

print(f"  Total successful Turn Off actions (weekly): {total_successful_turn_offs}")
print(f"  Mistakes identified: {num_mistakes}")
print(f"  Weekly mistake rate: {weekly_mistake_rate:.2f}%")

# Average profit lost per mistake
avg_profit_per_mistake = total_profit_lost / num_mistakes if num_mistakes > 0 else 0
print(f"  Average profit lost per mistake: ${avg_profit_per_mistake:,.2f}")

# Projection section with clear caveats
print("\n" + "=" * 80)
print("PROJECTION (ORDER-OF-MAGNITUDE ESTIMATE ONLY)")
print("=" * 80)

print("\n⚠️  IMPORTANT CAVEATS:")
print(f"  • Sample size: Only {unique_adsets} unique adsets over 1 week of data")
print("  • ROI decay over time is not modeled")
print("  • Assumes constant mistake rate (may vary seasonally)")
print("  • This is an order-of-magnitude estimate only, NOT a forecast")
print("  • Actual results may vary significantly")

# Extrapolate to monthly and annual
weeks_per_month = 4.33  # Average weeks per month
weeks_per_year = 52

monthly_mistakes_projected = num_mistakes * weeks_per_month
monthly_profit_lost_projected = total_profit_lost * weeks_per_month

annual_mistakes_projected = num_mistakes * weeks_per_year
annual_profit_lost_projected = total_profit_lost * weeks_per_year

print(f"\nProjected Monthly Impact (if pattern continues):")
print(f"  Estimated mistakes per month: {monthly_mistakes_projected:.1f}")
print(f"  Estimated profit lost per month: ${monthly_profit_lost_projected:,.2f}")

print(f"\nProjected Annual Impact (if pattern continues):")
print(f"  Estimated mistakes per year: {annual_mistakes_projected:.1f}")
print(f"  Estimated profit lost per year: ${annual_profit_lost_projected:,.2f}")

# Executive Summary
print("\n" + "=" * 80)
print("EXECUTIVE SUMMARY")
print("=" * 80)

print("\n📊 CONFIDENT WEEKLY FIGURES:")
print(f"  • {unique_adsets} unique adsets affected")
print(f"  • {num_mistakes} mistake events (after deduplication)")
print(f"  • ${total_profit_lost:,.2f} profit lost in the observed week")
print(f"  • {weekly_mistake_rate:.2f}% of Turn Off actions were mistakes")

if removed_count > 0:
    print(f"\n🔍 SYSTEM OBSERVATION:")
    print(f"  • {removed_count} duplicate firing(s) detected")
    print(f"  • Possible idempotency gap in rule execution system")

print(f"\n📈 CAVEATED PROJECTIONS (Order-of-magnitude only):")
print(f"  • Monthly: ~${monthly_profit_lost_projected:,.2f} potential profit loss")
print(f"  • Annual: ~${annual_profit_lost_projected:,.2f} potential profit loss")
print(f"  ⚠️  Based on {unique_adsets} adsets over 1 week - not a forecast")

# Write to INVESTIGATION.md
print("\n" + "=" * 80)
print("WRITING TO INVESTIGATION.MD")
print("=" * 80)

investigation_content = f"""
## Financial Impact Quantification

### Delayed Attribution Finding

Analysis of Turn Off rule executions revealed that **{num_mistakes} cases** (affecting **{unique_adsets} unique adsets**) were likely mistakes caused by incomplete attribution at evaluation time. In these cases:

- The rule observed negative ROI at the time of evaluation
- However, the finalized same-day performance showed positive profit
- This indicates that conversions were still being attributed after the rule fired

**Pattern observed**: Most mistakes occurred late in the day (evening hours), suggesting attribution lag is most severe near end-of-day when conversions are still being attributed to earlier ad interactions.

### Duplicate Firing Observation

During deduplication analysis, **{removed_count} duplicate action(s)** were detected where the same adset was turned off multiple times on the same day.

**Observation**: This pattern suggests a possible system idempotency gap where the rule may not check current adset status before re-firing on its 30-minute schedule.

**Caveat**: This is an observation based on the data pattern, not a confirmed root cause, as we don't have direct evidence of the underlying mechanism causing multiple firings.

### Confident Weekly Impact (Deduplicated Data)

Based on the observed week of data:

- **Unique adsets affected**: {unique_adsets}
- **Mistake events**: {num_mistakes} (after deduplication)
- **Combined daily spend**: ${total_spend:,.2f}
- **Combined daily profit lost**: ${total_profit_lost:,.2f}
- **Mistake rate**: {weekly_mistake_rate:.2f}% of successful Turn Off actions
- **Average profit lost per mistake**: ${avg_profit_per_mistake:,.2f}

**This is the only figure we can state with confidence from the available data.**

### Caveated Projections (Order-of-Magnitude Estimate Only)

If the observed pattern continues (with significant caveats):

**Monthly Projection**:
- Estimated mistakes: ~{monthly_mistakes_projected:.1f}
- Estimated profit lost: ~${monthly_profit_lost_projected:,.2f}

**Annual Projection**:
- Estimated mistakes: ~{annual_mistakes_projected:.1f}
- Estimated profit lost: ~${annual_profit_lost_projected:,.2f}

**⚠️ Important Limitations**:
- Sample size is only {unique_adsets} unique adsets over 1 week of data
- ROI decay over time is not modeled
- Assumes constant mistake rate (may vary seasonally or with campaign changes)
- This is an order-of-magnitude estimate only, NOT a forecast
- Actual results may vary significantly from these projections

### Recommendation

The confident weekly loss of ${total_profit_lost:,.2f} from {num_mistakes} preventable mistakes suggests that implementing attribution-aware rule logic (e.g., waiting longer before evaluating same-day performance, or using multi-day trends instead of intraday ROI) could provide measurable value.

---
*Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Data Period: Week of June 6-12, 2026*
"""

# Check if INVESTIGATION.md exists and handle idempotent updates
investigation_file = 'INVESTIGATION.md'
section_heading = "## Financial Impact Quantification"

if os.path.exists(investigation_file):
    print(f"  Updating existing {investigation_file}...")
    
    # Read existing content
    with open(investigation_file, 'r') as f:
        existing_content = f.read()
    
    # Check if the section already exists
    if section_heading in existing_content:
        print(f"  Removing old '{section_heading}' section for idempotent update...")
        
        # Find the start of the section
        section_start = existing_content.find(section_heading)
        
        # Find the next ## heading or end of file
        next_section_start = existing_content.find("\n## ", section_start + len(section_heading))
        
        if next_section_start == -1:
            # No next section, remove to end of file
            updated_content = existing_content[:section_start].rstrip() + "\n"
        else:
            # Remove from this section to the next section
            updated_content = existing_content[:section_start] + existing_content[next_section_start + 1:]
        
        # Write back without the old section
        with open(investigation_file, 'w') as f:
            f.write(updated_content)
        
        # Append new section
        with open(investigation_file, 'a') as f:
            f.write(investigation_content)
    else:
        # Section doesn't exist, just append
        print(f"  Appending new section to {investigation_file}...")
        with open(investigation_file, 'a') as f:
            f.write(investigation_content)
else:
    print(f"  Creating new {investigation_file}...")
    header = f"""# Marketing Automation Investigation

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

This document contains findings from the analysis of automated rule executions and their impact on campaign performance.

"""
    with open(investigation_file, 'w') as f:
        f.write(header + investigation_content)

print(f"  ✓ Successfully written to {investigation_file}")

print("\n" + "=" * 80)
print("IMPACT QUANTIFICATION COMPLETE")
print("=" * 80)
