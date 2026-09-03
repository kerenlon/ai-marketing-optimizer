import pandas as pd
import os

def main():
    print("Loading data for overlap evaluation...")
    
    agent_path = 'data/agent_decisions.csv'
    rules_path = 'data/rule_executions.csv'
    buyers_path = 'data/buyer_actions.csv'

    # 1. Load Agent Decisions and filter for actual LLM calls
    agent_df = pd.read_csv(agent_path)
    llm_decisions = agent_df[~agent_df['reasoning'].str.startswith('Pre-check escalation', na=False)].copy()
    llm_decisions['decision_date'] = llm_decisions['decision_date'].astype(str)

    # 2. Check overlap with Auto-Rules
    if os.path.exists(rules_path):
        rules_df = pd.read_csv(rules_path)
        # Using the exact column name 'action_date' found in the file
        rules_df['date'] = rules_df['action_date'].astype(str)
        
        rules_overlap = pd.merge(
            llm_decisions, rules_df, 
            left_on=['adset_id', 'decision_date'], 
            right_on=['adset_id', 'date'], 
            how='inner'
        )
        print(f"\n--- Overlaps with Auto-Rules ---")
        print(f"Total found: {len(rules_overlap)}")
        if not rules_overlap.empty:
            print(rules_overlap[['adset_id', 'decision_date', 'action', 'rule_name']].drop_duplicates().head())
    else:
        print(f"File not found: {rules_path}")

    # 3. Check overlap with Human Buyers
    if os.path.exists(buyers_path):
        buyers_df = pd.read_csv(buyers_path)
        # The brief mentions 'timestamp' for buyers, but we check common names just in case
        time_col = next((col for col in ['timestamp', 'action_date', 'date', 'action_time'] if col in buyers_df.columns), None)
        
        if time_col:
            buyers_df['date'] = buyers_df[time_col].astype(str).str[:10]
            buyers_overlap = pd.merge(
                llm_decisions, buyers_df, 
                left_on=['adset_id', 'decision_date'], 
                right_on=['adset_id', 'date'], 
                how='inner'
            )
            print(f"\n--- Overlaps with Human Buyers ---")
            print(f"Total found: {len(buyers_overlap)}")
            if not buyers_overlap.empty:
                print(buyers_overlap[['adset_id', 'decision_date', 'action', 'event_type']].drop_duplicates().head())
        else:
            print(f"\n[Error] Could not find a time column in buyers_df. Columns are: {buyers_df.columns.tolist()}")
    else:
        print(f"File not found: {buyers_path}")

if __name__ == "__main__":
    main()