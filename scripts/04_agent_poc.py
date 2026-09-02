"""
Task C: Agent POC - Analyst Agent Implementation
Demonstrates LLM-based budget decision making with proper guardrails and cost tracking.
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

# Claude Haiku 4.5 - cheapest current model (Sept 2026)
# $1/MTok input, $5/MTok output
MODEL_NAME = "claude-haiku-4-5-20251001"
COST_PER_1M_INPUT = 1.0
COST_PER_1M_OUTPUT = 5.0

VALID_ACTIONS = {'scale_up', 'scale_down', 'pause', 'keep', 'escalate'}

# Cost tracking
cost_tracker = {
    'calls': [],
    'total_input_tokens': 0,
    'total_output_tokens': 0,
    'total_cost': 0.0
}

BUDGET_CAP = 10.0  # $10 hard cap

# Define dtype specifications for ID columns
DTYPE_SPECS = {
    'campaign_adset_metadata.csv': {'adset_id': str, 'campaign_id': str},
    'daily_adset_performance.csv': {'adset_id': str, 'fb_ad_account_id': str},
    'rule_executions.csv': {'adset_id': str, 'campaign_id': str, 'account_id': str},
    'buyer_actions.csv': {'adset_id': str},
    'auto_rules.csv': {}
}

print("=" * 80)
print("TASK C: AGENT POC - ANALYST AGENT")
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
    """
    Build compact context for a single adset on a specific date.

    Args:
        adset_id: Adset ID to analyze
        date: Date to analyze (YYYY-MM-DD format)

    Returns:
        Compact dict with all relevant context
    """
    # Get adset metadata
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

    # Get last 3 days of performance (including the target date)
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
        # Handle nulls explicitly
        for key in perf_dict:
            if perf_dict[key] is None or (isinstance(perf_dict[key], float) and pd.isna(perf_dict[key])):
                perf_dict[key] = None
        performance.append(perf_dict)

    # Check for recent rule executions (day before through decision date)
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
            'action_date': r[0],
            'action_time': r[1],
            'rule_name': r[2],
            'action_name': r[3],
            'old_budget': r[4],
            'new_budget': r[5]
        }
        for r in rule_rows
    ]

    # Check for recent buyer actions (day before through decision date)
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
            'action_time': b[0],
            'event_type': b[1],
            'old_budget': b[2],
            'new_budget': b[3],
            'note': b[4]
        }
        for b in buyer_rows
    ]

    # Build compact context
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
    """
    Deterministic pre-check for uncertainty conditions.
    Returns (should_escalate, reasons)

    Forces escalation when:
    - spend_day_no < 2 (insufficient data)
    - revenue/estimated_conversions is null AND spend > 0 (true delayed attribution)
    - conflicting rule or buyer action BEFORE the decision date (not on it —
      the action on the decision date itself is what we're evaluating, not a conflict)
    """
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
    """
    Strip markdown code fences if the model wrapped its JSON despite
    being instructed not to. Returns (cleaned_text, needed_stripping).
    """
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
    """
    Call Claude to make a budget decision.
    Returns decision dict with action, amount, confidence, reasoning, data_quality_flags.
    """
    global cost_tracker

    # Check budget cap before making call
    if cost_tracker['total_cost'] >= BUDGET_CAP:
        print(f"\n⚠️  BUDGET CAP REACHED: ${cost_tracker['total_cost']:.4f} >= ${BUDGET_CAP}")
        print("  Skipping LLM call to stay within budget.")
        return {
            'adset_id': context['adset_id'],
            'decision_date': context['decision_date'],
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': 'Budget cap reached, skipping LLM call',
            'data_quality_flags': ['budget_cap_reached']
        }

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

    # --- Step 1: call the API. Failures here are genuine api_error. ---
    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
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

    # --- Cost tracking happens as soon as we have a response, regardless
    #     of whether the JSON inside it turns out to be parseable. We paid
    #     for the tokens either way. ---
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

    # --- Step 2: parse the JSON. Failures here are json_parse_error, not api_error. ---
    raw_text = response.content[0].text
    cleaned_text, needed_stripping = _clean_json_text(raw_text)

    try:
        decision = json.loads(cleaned_text)
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"\n⚠️  API responded, but JSON parsing failed: {e}")
        print(f"  Raw response: {raw_text[:300]}")
        return {
            'adset_id': context['adset_id'],
            'decision_date': context['decision_date'],
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': f'Model returned invalid JSON: {str(e)}',
            'data_quality_flags': ['json_parse_error']
        }

    # --- Step 3: validate the content of an otherwise well-formed JSON payload. ---
    flags = list(decision.get('data_quality_flags') or [])

    if needed_stripping:
        flags.append('required_markdown_stripping')

    if decision.get('action') not in VALID_ACTIONS:
        print(f"\n⚠️  Model returned an invalid action: {decision.get('action')!r}")
        original_action = decision.get('action')
        decision['action'] = 'escalate'
        decision['confidence'] = 0.0
        flags.append('invalid_action')
        decision['reasoning'] = (
            f"Original model reasoning: {decision.get('reasoning', '')} "
            f"[OVERRIDDEN: model returned unrecognized action '{original_action}', "
            f"forced to escalate for human review]"
        )

    if decision.get('action') in {'scale_up', 'scale_down'} and not isinstance(decision.get('amount'), (int, float)):
        print(f"\n⚠️  Model chose {decision.get('action')} but amount is missing/invalid")
        decision['action'] = 'escalate'
        decision['confidence'] = 0.0
        flags.append('missing_amount_for_scale_action')

    decision['data_quality_flags'] = flags
    return decision


def make_decision(adset_id: str, date: str) -> dict:
    """
    Full decision pipeline: build context, pre-check, call LLM if needed.
    """
    print(f"\n{'=' * 80}")
    print(f"Decision for Adset {adset_id} on {date}")
    print(f"{'=' * 80}")

    context = build_context(adset_id, date)

    if 'error' in context:
        print(f"  ❌ {context['error']}")
        return {
            'adset_id': adset_id,
            'decision_date': date,
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': context['error'],
            'data_quality_flags': ['metadata_error']
        }

    should_escalate, reasons = flag_uncertainty(context)

    if should_escalate:
        print(f"  ⚠️  Pre-check triggered escalation: {reasons}")
        print("  Skipping LLM call (saving cost)")
        return {
            'adset_id': adset_id,
            'decision_date': date,
            'action': 'escalate',
            'amount': None,
            'confidence': 0.0,
            'reasoning': f'Pre-check escalation: {", ".join(reasons)}',
            'data_quality_flags': reasons
        }

    print("  ✓ Pre-check passed, calling LLM...")
    decision = call_analyst_agent(context)

    print(f"  Decision: {decision.get('action', 'unknown')}")
    print(f"  Confidence: {decision.get('confidence', 0.0):.2f}")
    if cost_tracker['calls']:
        print(f"  Cost this call: ${cost_tracker['calls'][-1]['cost']:.4f}")
    else:
        print("  Cost this call: $0.0000 (Skipped/Error)")

    return decision


# Select sample adsets for testing
print("\n[2] Selecting sample adsets for POC...")

# Known Task A mistake case: adset 31255165214890 on 2026-06-08
task_a_adset = '31255165214890'
task_a_date = '2026-06-08'

# Find an adset with spend_day_no < 2
early_adset_query = """
SELECT DISTINCT adset_id, date
FROM daily_adset_performance
WHERE spend_day_no < 2
AND date >= '2026-06-06'
LIMIT 1
"""
early_result = conn.execute(early_adset_query).fetchone()
early_adset = early_result[0] if early_result else None
early_date = early_result[1] if early_result else None

# Select 3 "random" active adsets — deterministic via hash() so the sample
# is reproducible across runs instead of changing every time (ORDER BY RANDOM()
# would pick a different set each run, which makes it hard to show "this exact
# run happened" during review).
random_adsets_query = """
SELECT DISTINCT p.adset_id, p.date
FROM daily_adset_performance p
JOIN campaign_adset_metadata m ON p.adset_id = m.adset_id
WHERE p.date BETWEEN '2026-06-10' AND '2026-06-12'
AND m.effective_status = 'ACTIVE'
AND p.spend_day_no >= 3
ORDER BY hash(p.adset_id || p.date)
LIMIT 3
"""
random_results = conn.execute(random_adsets_query).fetchall()

test_cases = [
    (task_a_adset, task_a_date, 'Task A mistake case'),
]

if early_adset:
    test_cases.append((early_adset, str(early_date), 'Early spend_day_no test'))

for adset_id, date in random_results:
    test_cases.append((str(adset_id), str(date), 'Random active adset'))

print(f"  Selected {len(test_cases)} test cases:")
for adset_id, date, description in test_cases:
    print(f"    - {adset_id} on {date}: {description}")

# Run decisions
print("\n[3] Running agent decisions...")
all_decisions = []

for adset_id, date, description in test_cases:
    decision = make_decision(adset_id, date)
    decision['test_case_description'] = description
    all_decisions.append(decision)

    print("\n  Decision JSON:")
    print(f"  {json.dumps(decision, indent=4)}")

# Print final cost summary
print("\n" + "=" * 80)
print("COST SUMMARY")
print("=" * 80)
print(f"Total LLM calls: {len(cost_tracker['calls'])}")
print(f"Total input tokens: {cost_tracker['total_input_tokens']:,}")
print(f"Total output tokens: {cost_tracker['total_output_tokens']:,}")
print(f"Total cost: ${cost_tracker['total_cost']:.4f}")
print(f"Budget remaining: ${BUDGET_CAP - cost_tracker['total_cost']:.4f}")

if cost_tracker['total_cost'] < BUDGET_CAP:
    print(f"✅ Within budget cap (${BUDGET_CAP})")
else:
    print(f"⚠️  Exceeded budget cap (${BUDGET_CAP})")

# Save decisions to CSV
print("\n[4] Saving decisions to CSV...")
decisions_df = pd.DataFrame(all_decisions)
output_file = 'data/agent_decisions.csv'
decisions_df.to_csv(output_file, index=False)
print(f"  ✓ Saved to {output_file}")

print("\n" + "=" * 80)
print("AGENT POC COMPLETE")
print("=" * 80)