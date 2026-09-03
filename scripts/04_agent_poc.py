"""
Task C: Agent POC - Analyst Agent Implementation
Demonstrates LLM-based budget decision making with proper guardrails and cost tracking.
Full-pass execution across all active adsets for the last 3 distinct dates with refined Resume & Budget logic.
"""

import pandas as pd
import duckdb
import json
import os
from dotenv import load_dotenv
import anthropic

# Load environment variables
load_dotenv()

# Initialize Anthropic client
client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

# Configuration & Constants
MODEL_NAME = "claude-haiku-4-5-20251001"
COST_PER_1M_INPUT = 1.0
COST_PER_1M_OUTPUT = 5.0
VALID_ACTIONS = {'scale_up', 'scale_down', 'pause', 'keep', 'escalate'}
DEBUG_MODE = False
BUDGET_CAP = 10.0  # $10 hard cap
AVG_COST_PER_LLM_CALL = 0.0032  # Empirical benchmark from prior successful run
OUTPUT_FILE = 'data/agent_decisions.csv'

# Cost tracking
cost_tracker = {
    'calls': [],
    'total_input_tokens': 0,
    'total_output_tokens': 0,
    'total_cost': 0.0
}

# Define dtype specifications for ID columns
DTYPE_SPECS = {
    'campaign_adset_metadata.csv': {'adset_id': str, 'campaign_id': str},
    'daily_adset_performance.csv': {'adset_id': str, 'fb_ad_account_id': str},
    'rule_executions.csv': {'adset_id': str, 'campaign_id': str, 'account_id': str},
    'buyer_actions.csv': {'adset_id': str},
    'auto_rules.csv': {}
}

print("=" * 80)
print("TASK C: AGENT POC - ANALYST AGENT (FULL PASS WITH REFINED RESUME)")
print("=" * 80)

# Load data
print("\n[1] Loading data with proper dtype handling...")
DATA_DIR = 'data/'
FILES = [
    'campaign_adset_metadata.csv',
    'daily_adset_performance.csv',
    'rule_executions.csv',
    'buyer_actions.csv',
    'auto_rules.csv'
]

dataframes = {}
for file in FILES:
    file_path = f"{DATA_DIR}{file}"
    dtype_spec = DTYPE_SPECS.get(file, {})
    df = pd.read_csv(file_path, dtype=dtype_spec)
    table_name = file.replace('.csv', '')
    dataframes[table_name] = df

# Create DuckDB connection
conn = duckdb.connect(':memory:')
for table_name, df in dataframes.items():
    conn.register(table_name, df)
print("  ✓ Data loaded and registered in DuckDB")


def build_context(adset_id: str, date: str) -> dict:
    """Build compact context for a single adset on a specific date."""
    metadata_query = """
    SELECT
        adset_id,
        campaign_id,
        adset_name,
        effective_status,
        daily_budget,
        bid_strategy,
        objective,
        optimization_goal
    FROM campaign_adset_metadata
    WHERE adset_id = ?
    LIMIT 1
    """
    metadata = conn.execute(metadata_query, [adset_id]).fetchone()

    if not metadata:
        return {'error': f'Adset {adset_id} not found in metadata'}

    perf_query = """
    SELECT
        date,
        spend,
        revenue,
        profit,
        roi,
        impressions,
        clicks,
        fb_conversions,
        estimated_conversions,
        spend_day_no
    FROM daily_adset_performance
    WHERE adset_id = ?
    AND date <= ?
    ORDER BY date DESC
    LIMIT 3
    """
    perf_rows = conn.execute(perf_query, [adset_id, date]).fetchall()
    perf_cols = ['date', 'spend', 'revenue', 'profit', 'roi', 'impressions',
                 'clicks', 'fb_conversions', 'estimated_conversions', 'spend_day_no']

    performance = []
    for row in perf_rows:
        perf_dict = dict(zip(perf_cols, row))
        for key in perf_dict:
            if perf_dict[key] is None or (isinstance(perf_dict[key], float) and pd.isna(perf_dict[key])):
                perf_dict[key] = None
        performance.append(perf_dict)

    rule_query = """
    SELECT
        action_date,
        action_time,
        rule_name,
        action_name,
        old_budget,
        new_budget
    FROM rule_executions
    WHERE adset_id = ?
    AND CAST(action_date AS DATE) >= CAST(? AS DATE) - INTERVAL '1 day'
    AND CAST(action_date AS DATE) <= CAST(? AS DATE)
    ORDER BY action_time DESC
    LIMIT 5
    """
    rule_rows = conn.execute(rule_query, [adset_id, date, date]).fetchall()
    recent_rules = [
        {
            'action_date': r[0], 'action_time': r[1], 'rule_name': r[2],
            'action_name': r[3], 'old_budget': r[4], 'new_budget': r[5]
        }
        for r in rule_rows
    ]

    buyer_query = """
    SELECT
        action_time,
        event_type,
        old_budget,
        new_budget,
        note
    FROM buyer_actions
    WHERE adset_id = ?
    AND CAST(action_time AS DATE) >= CAST(? AS DATE) - INTERVAL '1 day'
    AND CAST(action_time AS DATE) <= CAST(? AS DATE)
    ORDER BY action_time DESC
    LIMIT 5
    """
    buyer_rows = conn.execute(buyer_query, [adset_id, date, date]).fetchall()
    recent_buyer_actions = [
        {
            'action_time': b[0], 'event_type': b[1], 'old_budget': b[2],
            'new_budget': b[3], 'note': b[4]
        }
        for b in buyer_rows
    ]

    context = {
        'adset_id': adset_id,
        'decision_date': date,
        'metadata': {
            'campaign_id': metadata[1],
            'adset_name': metadata[2],
            'status': metadata[3],
            'current_budget': float(metadata[4]) if metadata[4] is not None else None,
            'bid_strategy': metadata[5],
            'objective': metadata[6],
            'optimization_goal': metadata[7]
        },
        'performance_last_3_days': performance,
        'recent_rule_actions': recent_rules,
        'recent_buyer_actions': recent_buyer_actions
    }

    return context


def flag_uncertainty(context: dict) -> tuple[bool, list[str]]:
    """Deterministic pre-check for uncertainty conditions."""
    reasons = []

    if 'error' in context:
        return True, ['metadata_not_found']

    perf = context.get('performance_last_3_days', [])
    if not perf:
        return True, ['no_performance_data']

    today_perf = perf[0]
    decision_date = context.get('decision_date')

    spend_day_no = today_perf.get('spend_day_no')
    if spend_day_no is None or spend_day_no < 2:
        reasons.append(f'insufficient_data_days_{spend_day_no}')

    spend = today_perf.get('spend', 0) or 0
    if spend > 0 and today_perf.get('revenue') is None:
        reasons.append('null_revenue_with_spend')

    if spend > 0 and today_perf.get('estimated_conversions') is None:
        reasons.append('null_conversions_with_spend')

    recent_rules = context.get('recent_rule_actions', [])
    prior_rules = [r for r in recent_rules if r.get('action_date') != decision_date]
    if prior_rules:
        reasons.append(f'recent_rule_action_conflict_{len(prior_rules)}')

    recent_buyers = context.get('recent_buyer_actions', [])
    prior_buyers = [
        b for b in recent_buyers
        if b.get('action_time') and str(b['action_time'])[:10] != decision_date
    ]
    if prior_buyers:
        reasons.append(f'recent_buyer_action_conflict_{len(prior_buyers)}')

    should_escalate = len(reasons) > 0
    return should_escalate, reasons


def _clean_json_text(raw_text: str) -> tuple[str, bool]:
    text = raw_text.strip()
    needed_stripping = False

    if text.startswith("```"):
        needed_stripping = True
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

    return text, needed_stripping


def call_analyst_agent(context: dict) -> dict:
    global cost_tracker

    system_prompt = """You are a media buying analyst AI agent. Your role is to analyze adset performance data and recommend budget actions.

You must return ONLY valid JSON matching this exact schema:
{
  "adset_id": "string",
  "decision_date": "YYYY-MM-DD",
  "action": "scale_up|scale_down|pause|keep|escalate",
  "amount": null or float (new daily budget if action is scale_up/scale_down),
  "confidence": 0.0-1.0,
  "reasoning": "string explaining your decision",
  "data_quality_flags": ["list", "of", "concerns"]
}

Action definitions:
- scale_up: Increase budget (provide new amount)
- scale_down: Decrease budget (provide new amount)
- pause: Turn off the adset
- keep: No change needed
- escalate: Uncertain, needs human review

Guidelines:
- Consider ROI, profit trends, spend efficiency
- Be conservative with limited data
- Flag data quality issues
- Explain your reasoning clearly
- Use escalate when uncertain

Return ONLY the JSON, no other text. Do not wrap it in markdown code fences."""

    user_prompt = f"""Analyze this adset and recommend a budget action:

{json.dumps(context, indent=2, default=str)}

Return your decision as JSON following the schema."""

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
    except Exception as e:
        print(f"\n❌ Error calling API: {e}")
        return {
            'adset_id': context['adset_id'],
            'decision_date': context['decision_date'],
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': f'API error: {str(e)}',
            'data_quality_flags': ['api_error']
        }

    if DEBUG_MODE:
        print(f"--- API RESPONSE DEBUG ---")
        print(f"stop_reason: {response.stop_reason}")
        print(f"number of content blocks: {len(response.content)}")
        for i, block in enumerate(response.content):
            print(f"  block {i}: type={block.type}, repr={repr(block)[:200]}")
        print(f"repr of content[0].text: {repr(response.content[0].text) if response.content else 'NO CONTENT BLOCKS'}")
        print(f"--------------------------")

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    call_cost = (input_tokens / 1_000_000 * COST_PER_1M_INPUT) + \
                (output_tokens / 1_000_000 * COST_PER_1M_OUTPUT)

    cost_tracker['total_input_tokens'] += input_tokens
    cost_tracker['total_output_tokens'] += output_tokens
    cost_tracker['total_cost'] += call_cost
    cost_tracker['calls'].append({
        'adset_id': context['adset_id'],
        'date': context['decision_date'],
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cost': call_cost
    })

    raw_text = response.content[0].text
    cleaned_text, needed_stripping = _clean_json_text(raw_text)

    try:
        decision = json.loads(cleaned_text)
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"\n⚠️  API responded, but JSON parsing failed: {e}")
        return {
            'adset_id': context['adset_id'],
            'decision_date': context['decision_date'],
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': f'Model returned invalid JSON: {str(e)}',
            'data_quality_flags': ['json_parse_error']
        }

    flags = list(decision.get('data_quality_flags') or [])
    if needed_stripping:
        flags.append('required_markdown_stripping')

    if decision.get('action') not in VALID_ACTIONS:
        original_action = decision.get('action')
        decision['action'] = 'escalate'
        decision['confidence'] = 0.0
        flags.append('invalid_action')
        decision['reasoning'] = (
            f"Original model reasoning: {decision.get('reasoning', '')} "
            f"[OVERRIDDEN: unrecognized action '{original_action}']"
        )

    if decision.get('action') in {'scale_up', 'scale_down'} and not isinstance(decision.get('amount'), (int, float)):
        decision['action'] = 'escalate'
        decision['confidence'] = 0.0
        flags.append('missing_amount_for_scale_action')

    decision['data_quality_flags'] = flags
    return decision


# [STEP 2] Full pass query: get last 3 distinct dates and all active adset-date combos
print("\n[2] Building full test set across last 3 distinct dates for ACTIVE adsets...")

dates_query = """
SELECT DISTINCT date 
FROM daily_adset_performance 
ORDER BY date DESC 
LIMIT 3
"""
last_3_dates = [row[0] for row in conn.execute(dates_query).fetchall()]
print(f"  Target dates identified: {last_3_dates}")

placeholders = ', '.join(['?'] * len(last_3_dates))
combos_query = f"""
SELECT DISTINCT p.adset_id, p.date
FROM daily_adset_performance p
JOIN campaign_adset_metadata m ON p.adset_id = m.adset_id
WHERE m.effective_status = 'ACTIVE'
AND p.date IN ({placeholders})
ORDER BY p.date DESC, p.adset_id
"""
test_combinations = conn.execute(combos_query, last_3_dates).fetchall()
total_combos = len(test_combinations)
print(f"  Total ACTIVE adset-date combinations found: {total_combos:,}")


# [STEP 3] Run pre-checks on ALL combinations first (free, no API calls)
print("\n[3] Running pre-checks across all combinations...")
precheck_results = []
escalated_count = 0
llm_candidate_count = 0

for adset_id, date in test_combinations:
    context = build_context(str(adset_id), str(date))
    escalate, reasons = flag_uncertainty(context)
    
    if escalate:
        escalated_count += 1
    else:
        llm_candidate_count += 1
        
    precheck_results.append({
        'adset_id': str(adset_id),
        'date': str(date),
        'context': context,
        'escalated': escalate,
        'reasons': reasons
    })

# [RESUME CHECK] Build processed_set excluding budget-exhausted placeholders
processed_set = set()
resumed_count = 0

if os.path.exists(OUTPUT_FILE):
    try:
        existing_df = pd.read_csv(OUTPUT_FILE, dtype={'adset_id': str})
        if 'adset_id' in existing_df.columns and 'decision_date' in existing_df.columns:
            for _, row in existing_df.iterrows():
                flags = str(row.get('data_quality_flags', ''))
                # Exclude placeholders so they remain eligible for processing
                if 'not_processed_budget_exhausted' not in flags:
                    processed_set.add((str(row['adset_id']), str(row['decision_date'])))
            resumed_count = len(processed_set)
    except Exception as e:
        print(f"  ⚠ Note: Could not parse existing checkpoint file for resume: {e}")

# Calculate estimated cost for remaining LLM candidates using effective_llm_candidates
effective_llm_candidates = max(0, llm_candidate_count - resumed_count)
estimated_cost = effective_llm_candidates * AVG_COST_PER_LLM_CALL

print("\n" + "=" * 80)
print("PRE-CHECK & COST SUMMARY REPORT")
print("=" * 80)
print(f"  Total combinations evaluated: {total_combos:,}")
print(f"  Escalated by pre-check (No LLM needed): {escalated_count:,} ({escalated_count/total_combos*100:.1f}%)")
print(f"  Reaching LLM Analyst pipeline: {llm_candidate_count:,}")
if resumed_count > 0:
    print(f"  Already processed (Resuming from checkpoint): {resumed_count:,} pairs")
print(f"  Estimated LLM calls to execute: {effective_llm_candidates:,}")
print(f"  Estimated LLM cost: ~${estimated_cost:.2f} (Hard cap: ${BUDGET_CAP:.2f})")
print("=" * 80)

# Confirm before proceeding
input("\nPress [Enter] to confirm summary and proceed to execution / decision processing...")


# [STEPS 4 & 5] Process decisions sequentially with refined resume, budget precedence and checkpointing
print("\n[4-5] Processing decisions and writing checkpoints to", OUTPUT_FILE, "...")

total_processed = 0
total_escalated_precheck = 0
total_sent_to_llm = 0
total_skipped_resume = 0
budget_exhausted = False

for item in precheck_results:
    adset_id = item['adset_id']
    date = item['date']
    
    # Check if already successfully processed (Resume Capability)
    if (adset_id, date) in processed_set:
        total_skipped_resume += 1
        continue

    total_processed += 1
    context = item['context']
    escalate = item['escalated']
    reasons = item['reasons']
    
    # Check if budget cap is already reached
    if cost_tracker['total_cost'] >= BUDGET_CAP:
        budget_exhausted = True

    # Check escalate FIRST (pre-check escalations are free and keep real reasons)
    if escalate:
        total_escalated_precheck += 1
        decision = {
            'adset_id': adset_id,
            'decision_date': date,
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': f'Pre-check escalation: {", ".join(reasons)}',
            'data_quality_flags': reasons
        }
    elif budget_exhausted:
        decision = {
            'adset_id': adset_id,
            'decision_date': date,
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': 'Budget cap exhausted, processing halted for remaining items',
            'data_quality_flags': ['not_processed_budget_exhausted']
        }
    else:
        total_sent_to_llm += 1
        print(f"  Calling LLM for Adset {adset_id} on {date} (Cost so far: ${cost_tracker['total_cost']:.4f})...")
        decision = call_analyst_agent(context)

    # Append decision immediately as checkpoint (Step 5)
    df_row = pd.DataFrame([decision])
    write_header = not os.path.exists(OUTPUT_FILE)
    df_row.to_csv(OUTPUT_FILE, mode='a', header=write_header, index=False)


# [STEP 6] Final Summary Printout
print("\n" + "=" * 80)
print("AGENT POC FULL-PASS EXECUTION COMPLETE - FINAL SUMMARY")
print("=" * 80)
print(f"  Total combinations skipped (Resumed): {total_skipped_resume:,}")
print(f"  Total combinations processed this run: {total_processed:,}")
print(f"  Total escalated via pre-check: {total_escalated_precheck:,}")
print(f"  Total sent to LLM: {total_sent_to_llm:,}")
print(f"  Total LLM API calls executed: {len(cost_tracker['calls']):,}")
print(f"  Total token usage: Input={cost_tracker['total_input_tokens']:,}, Output={cost_tracker['total_output_tokens']:,}")
print(f"  Total cost incurred: ${cost_tracker['total_cost']:.4f}")
print(f"  Budget remaining: ${BUDGET_CAP - cost_tracker['total_cost']:.4f}")
print(f"  Results checkpointed to: {OUTPUT_FILE}")
print("=" * 80)