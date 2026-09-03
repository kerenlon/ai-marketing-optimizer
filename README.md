# AI-Powered Marketing Optimizer POC

An analytical pipeline and autonomous decision agent framework for evaluating Meta Ads adset performance.

The system evaluates daily performance metrics, cross-references automated rule logs with manual media buyer actions, and employs a hybrid decision architecture (Deterministic SQL Pre-Checks + LLM Contextual Reasoning) to output structured budget decisions (`pause`, `scale_up`, `scale_down`, `keep`, or `escalate`).

---

## Project Metadata

* **Total Time Spent:** ~18-20 hours (exploratory data analysis, SQL investigation, agent implementation, checkpointing resilience testing, and documentation).
* **Where Corners Were Cut (POC Pragmatism):**

  * **Storage Architecture:** Utilized append-only local CSV checkpointing instead of deploying a transactional database (PostgreSQL/Redis) or task queue.
  * **Execution Pipeline:** Implemented sequential execution with rate-limit buffers rather than an asynchronous distributed worker pool (e.g., Celery).
  * **Feature Scope:** Restricted LLM prompt payloads to isolated adset metrics, recent spend, and rule history, omitting full account-level and cross-campaign aggregated context to minimize token footprint.
  * **Static Thresholds:** Enforced hardcoded pre-check safety boundaries (48-hour cold start, 24-hour buyer collision window) rather than optimizing dynamic thresholds via hyperparameter search.

---

## Architecture Overview

The system operates across three distinct stages to maximize execution safety, reduce latency, and control API expenditure:

| Layer                          | Functional Scope                                                                                            | Target Script                                                                                                 |
| :----------------------------- | :---------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------ |
| **1. Data Ingestion & Audit**  | Ingests raw Meta Ads data, validates schemas via DuckDB, and evaluates historical rule performance.         | `scripts/01_data_exploration.py`, `scripts/02_task_a_investigation.py`, `scripts/03_impact_quantification.py` |
| **2. Deterministic Pre-Check** | Filters unviable cases (cold starts, data sparsity, recent human edits) before triggering paid API calls.   | `scripts/04_agent_poc.py`                                                                                     |
| **3. LLM Decision Pipeline**   | Evaluates multi-day performance and rule history via Claude Haiku 4.5; generates structured JSON decisions. | `scripts/04_agent_poc.py`                                                                                     |

---

## Core Engineering Components

### 1. Deterministic SQL Pre-Check

Adsets with fewer than 48 hours of spend history or manual buyer modifications within the trailing 24 hours are automatically escalated. In production testing, this deterministic filter resolved 63.4% of all cases without incurring external LLM API costs.

### 2. LLM Contextual Evaluation

Cases passing the pre-check are formatted into structured prompts containing trailing 3-day spend, conversion volume, ROI trajectories, and rule logs. The model returns a typed JSON payload containing:

* `action`: One of `pause`, `scale_up`, `scale_down`, `keep`, or `escalate`.
* `confidence`: Float between 0.0 and 1.0.
* `reasoning`: Analytical justification for the recommendation.
* `data_quality_flags`: List of identified data anomalies or volatility indicators.

### 3. Checkpointing and State Recovery

State is persisted to `data/agent_decisions.csv` on every completed decision. If execution is interrupted by network failure or environment termination, the pipeline parses existing records on reboot and resumes without duplicate API calls or state corruption.

### 4. Runtime Cost Governance

The pipeline tracks token usage dynamically and halts execution if cumulative expenditure approaches the configured budget ceiling ($10.00).

---

## Repository Structure

```text
├── data/
│   ├── agent_decisions.csv         # Complete decision log with JSON payloads
│   └── task_a_mistakes.csv         # Documented historical rule errors
├── scripts/
│   ├── 01_data_exploration.py      # Data cleaning and dtype normalization
│   ├── 02_task_a_investigation.py  # Rule failure identification
│   ├── 03_impact_quantification.py # Financial impact analysis
│   ├── 04_agent_poc.py             # Pre-check engine and LLM agent
│   └── 05_evaluate_overlaps.py     # Evaluates agent decisions vs. historical rule/buyer actions
├── ARCHITECTURE.md                 # System architecture specifications
├── DECISIONS.md                    # Technical and design decision records
├── INVESTIGATION.md                # Quantitative review of static rule failures
├── RESULTS.md                      # Full execution metrics, costs, and analysis
├── requirements.txt                # Dependency manifest
└── .gitignore                      # Git exclusion rules
```

## Installation & Usage

### 1. Environment Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the root directory:

```text
ANTHROPIC_API_KEY=your_api_key_here
```

### 3. Execution Order

```bash
python3 scripts/01_data_exploration.py
python3 scripts/02_task_a_investigation.py
python3 scripts/03_impact_quantification.py
python3 scripts/04_agent_poc.py
python3 scripts/05_evaluate_overlaps.py
```

## Key Results Summary

* **Combinations Evaluated:** 2,064 across a trailing 3-day window.
* **Pre-Check Filter Rate:** 1,308 cases (63.4%) resolved without LLM calls.
* **LLM Calls Executed:** 756 evaluations.
* **Total Expenditure:** ~$1.90 (Total across runs; final execution batch was $1.29 against a $10.00 ceiling).
* **Overall Decision Distribution:** 2,020 Escalate (97.9%), 37 Pause, 4 Scale Up, 2 Keep, 1 Scale Down.

For comprehensive metric breakdowns, model calibration data, and the shadow-mode production roadmap, see `RESULTS.md`.
