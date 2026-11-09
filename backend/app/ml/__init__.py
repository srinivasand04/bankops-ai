"""Classical machine learning on BankOps AI data (see documents/ml.md).

Seven tasks, each comparing several algorithms on a time-based split:
  mttr          - regression: how long will this incident take to resolve?
  sla_breach    - classification: will this incident breach its resolution SLA?
  change_risk   - classification: will this change cause an incident?
  routing       - text classification: which category / team, from the title and description?
  similar       - KNN: which past incidents look like this one? (pgvector)
  clusters      - K-Means: which recurring incident patterns exist?
  forecast      - time series: incident volume forecast and metric anomaly detection

Predictions are suggestions. They never change an incident; people (and the AI analyst, which cites
them as ML-PRED-<id>) treat them as probabilistic evidence.
"""

SEED = 42  # every random step uses this seed so results are reproducible
