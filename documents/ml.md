# Machine learning (ML Lab)

Classical machine learning on the incident history. Each task compares several algorithms on the
**same time-based split**: the oldest 75% of records train the models and the newest 25% test them.
The model is never tested on data it has seen, and nothing from the future leaks in. The best
algorithm on the task's main metric becomes the **active** model used for predictions; the others
stay in the comparison.

Code: `backend/app/ml/`. That folder holds `features.py`, `datasets.py`, `evaluation.py`,
`registry.py`, `trainer.py`, `service.py`, `bundle.py`, plus one file per task in `tasks/`. Each task
file starts with a plain explanation of what its algorithms do and why they fit.

## Commands

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.ml list                     # tasks and their active models
.\.venv\Scripts\python.exe -m app.ml train --task sla_breach  # one task
.\.venv\Scripts\python.exe -m app.ml train-all                # all eight (~1 minute on 4,000 incidents)
.\.venv\Scripts\python.exe -m app.ml export-bundle            # ship active models to backend/ml_bundle (hosted demo)
pip install -r requirements-ml-extra.txt                      # optional: add XGBoost + LightGBM to the SLA comparison
```

Training needs the large synthetic dataset (`scripts/generate_synthetic.py` + `app.ingestion load
datasets/synthetic_large`). Each seed is fixed (`app.ml.SEED = 42`). The UI's **Train all models**
button runs the same training in the background (incident managers and admins only).

## No data leakage

| Prediction | Known at that moment (features) | Never used as a feature |
|---|---|---|
| Incident at creation | severity, category, application and tier, hour / weekday / night / business hours, changes deployed on the app in the previous 24 h (and how many were high-risk), incidents on the app in the previous 30 days, number of dependencies and dependents | resolution time, SLA outcome, assignee, anything after creation |
| Change at deployment | type, declared risk, scope (components), hour, Friday, weekend, outside the approved change window, tier, the app's earlier changes that caused incidents (90 days) | whether this change caused an incident |

The real BPI 2014 incidents are left out of training: they are from 2014 and have no free text. They
still get predictions.

## Tasks and results

Results below are on the 4,000-incident synthetic dataset (seed 42), with test sets of the newest
1,000 incidents or 164 changes.

| # | Task | Algorithms compared | Main metric | Result (used model in **bold**) |
|---|---|---|---|---|
| 1 | Resolution time (regression) | **Linear regression on log(MTTR)**, gradient boosting | MAE (minutes), R² | **495 min, R² 0.37** vs 523 min, R² 0.34 |
| 2 | SLA breach at creation | logistic regression, **random forest**, XGBoost, LightGBM | ROC-AUC | 0.644 / **0.646** / 0.632 / 0.642 |
| 3 | Change risk | decision tree (depth 4), random forest, **gradient boosting** | ROC-AUC | 0.618 / 0.691 / **0.764** |
| 4 | Category routing from text | TF-IDF + Naive Bayes, **TF-IDF + linear SVM**, RBF SVM (1,500-row sample) | macro-F1 | 0.838 / **0.838** / 0.836; team routing accuracy 0.88 |
| 5 | Similar incidents | **TF-IDF + SVD (64-d) vectors in pgvector, KNN (k=7, cosine)** | macro-F1 (category from neighbours) | **0.807** |
| 6 | Incident patterns | **K-Means**, k = 4-16 by elbow + silhouette | silhouette, purity vs category | **k = 10, silhouette 0.42, purity 0.80** |
| 7a | Weekly volume forecast | seasonal naive, **Holt-Winters (damped trend)** | MAE (incidents / week) | 2.36 vs **2.18** |
| 7b | Metric anomalies | **rolling z-score**, seasonal residual | F1 of "alert in the 3 h before an incident" | **0.41** (precision 0.62, recall 0.31) vs 0.37 (precision 0.26, recall 0.62) |

### What the numbers say

- **SLA breach is hard at creation time** (AUC about 0.65). Whether an incident breaches depends
  mostly on what happens after it is logged, which the model cannot see. All four algorithms land
  within 0.015 of each other, so the extra complexity of XGBoost and LightGBM buys nothing here.
  Calibration shows the probabilities are too low at the top end.
- **Change risk has real signal** (AUC 0.76): Friday deployments, changes outside the change window
  and the app's recent failures all matter. The bias-variance curve is the textbook shape: as tree
  depth grows from 1 to 12, the train score rises to 0.99 while the test score peaks at depth 3-4
  (0.71) and then falls (overfitting).
- **Linear regression beats gradient boosting on MTTR.** The log target already linearises most of
  the effect. The residual check backs this up: mean 0.00, skew 0.17, and no correlation with the
  fitted value.
- **Text routing is strong but not perfect** (macro-F1 0.84) because the generator deliberately
  writes 10-15% ambiguous text. Naive Bayes, the baseline, ties with the SVM.
- **K-Means rediscovers the categories** (80% purity) and labels clusters with meaningful terms
  ("cpu, peak, latency", "http, 5xx", "ended notok").
- **Anomaly detectors trade precision against recall.** The rolling z-score raises fewer, better
  alerts. The seasonal-residual detector catches twice as many incidents but with four times the
  false alarms.

## Where predictions appear

- **Incident page → ML insights:** SLA-breach probability with its band, predicted resolution time
  with the typical error, suggested category and team (flagged when it differs from what was
  recorded), the recurring pattern, and the 5 most similar past incidents (pgvector). Predictions
  are stored when an incident is created.
- **ML Lab → Scored changes:** the latest changes, each with its incident probability and reasons.
- **AI analysis and the agent team:** predictions enter the fact base as `ML-PRED-<id>` items with
  the model's name, version and test metrics. The prompt tells the AI to treat them as
  probabilistic evidence, never as facts.
- **API:** `GET /api/ml/tasks`, `GET /api/ml/runs`, `POST /api/ml/train` (manager+),
  `GET /api/ml/incidents/{id}/predictions`, `GET /api/ml/changes/{id}/risk`,
  `GET /api/ml/changes`.

Predictions never change severity, category, status or anything else on an incident.

## Storage

- `ml_model_runs`: one row per algorithm per training, with parameters, metrics, details (confusion
  matrix, importances, curves), train/test periods and `is_active`.
- `ml_predictions`: suggestions per incident or change, with the model card attached.
- `ml_incident_vectors`: `vector(64)` per incident (pgvector) for similarity search.
- Model files: `ML_ARTIFACTS_DIR` (`backend/ml_artifacts`, bind-mounted into Docker).

## Hosted demo and image size

- **Bundle:** the hosted database only holds the 15 demo incidents, which is too few to train on.
  `export-bundle` copies the active models (about 15 MB) and all run records into `backend/ml_bundle/`.
  At startup an empty `ml_model_runs` table is filled from it (`ML_BUNDLE_AUTOLOAD`), and the demo
  incidents are embedded on first use.
- **Image size:** scikit-learn, pandas, SciPy and statsmodels take the Docker image from about 450 MB
  to about 1 GB. XGBoost and LightGBM would roughly double that again, so they are optional
  (`requirements-ml-extra.txt`).
- **Memory:** with all models loaded the API uses about 260 MB.

## Limitations

- **Synthetic signal:** I designed the generator's rules (see [synthetic-data.md](synthetic-data.md)),
  so the models learn rules I wrote. Real-world scores would be lower and noisier.
- **SHAP not used:** explanations are logistic contributions, tree importances and permutation
  importance. SHAP was left out to keep the image smaller.
- **No sentence-transformers:** embeddings are TF-IDF + SVD, so similarity is lexical (shared words).
- **Simple anomaly scoring:** detectors are judged only by alerts in the 3 hours before incidents;
  real alerting would also weigh business impact and alert fatigue.
