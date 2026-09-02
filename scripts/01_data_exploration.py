"""
Data Exploration Script
Loads CSV files from data/ folder with proper dtype handling for ID columns
to prevent precision loss and scientific notation.
"""

import pandas as pd
import duckdb

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
        # Note: campaign_id does not exist in this file
    },
    'auto_rules.csv': {
        # No ID columns needed
    }
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
print("LOADING CSV FILES WITH DTYPE SPECIFICATIONS")
print("=" * 80)

# Load all CSV files into pandas DataFrames
dataframes = {}

for file in FILES:
    file_path = f"{DATA_DIR}{file}"
    dtype_spec = DTYPE_SPECS.get(file, {})
    
    print(f"\nLoading {file}...")
    print(f"  dtype specification: {dtype_spec if dtype_spec else 'None (default types)'}")
    
    df = pd.read_csv(file_path, dtype=dtype_spec)
    
    # Store with table name (remove .csv extension)
    table_name = file.replace('.csv', '')
    dataframes[table_name] = df
    
    print(f"  ✓ Loaded {len(df):,} rows")

print("\n" + "=" * 80)
print("CREATING DUCKDB IN-MEMORY DATABASE")
print("=" * 80)

# Create DuckDB in-memory connection
conn = duckdb.connect(':memory:')

# Register all DataFrames as DuckDB tables
for table_name, df in dataframes.items():
    conn.register(table_name, df)
    print(f"✓ Registered table: {table_name}")

print("\n" + "=" * 80)
print("VERIFICATION: ROW COUNTS")
print("=" * 80)

for table_name in dataframes.keys():
    row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print(f"{table_name:30s} : {row_count:,} rows")

print("\n" + "=" * 80)
print("VERIFICATION: ID COLUMN DTYPES AND SAMPLE DATA")
print("=" * 80)

# Verify ID columns for each DataFrame
for file, dtype_spec in DTYPE_SPECS.items():
    if not dtype_spec:
        continue
    
    table_name = file.replace('.csv', '')
    df = dataframes[table_name]
    
    print(f"\n{table_name.upper()}")
    print("-" * 80)
    
    for col_name in dtype_spec.keys():
        if col_name in df.columns:
            print(f"\nColumn: {col_name}")
            print(f"  dtype: {df[col_name].dtype}")
            print(f"  Sample values (first 3 rows):")
            for idx, val in enumerate(df[col_name].head(3), 1):
                print(f"    [{idx}] {val}")
        else:
            print(f"\nColumn: {col_name}")
            print(f"  ⚠ WARNING: Column not found in DataFrame!")

print("\n" + "=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)
print("\nAll DataFrames loaded successfully with proper dtype handling.")
print("ID columns are stored as strings to prevent precision loss.")
print("DuckDB in-memory database is ready for querying.")
