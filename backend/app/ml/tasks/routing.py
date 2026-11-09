"""Task 4 - Category and team routing from the incident's title and description (text classification).

TF-IDF turns text into numbers: each word gets a weight that is high when it is frequent in this
incident but rare overall ("ORA-00060" says more than "error").
Multinomial Naive Bayes multiplies per-word probabilities for each category - fast and a classic
baseline, but it assumes words are independent. A Linear SVM finds the boundary with the widest margin
between categories and usually wins on text. An RBF-kernel SVM can draw curved boundaries but is slow,
so it is trained on a sample - a fair illustration of the cost/benefit of kernels.
The synthetic text has ~10-15% ambiguous wording, so a perfect score is not expected.
"""

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC, LinearSVC
from sqlalchemy.orm import Session

from app.ml import SEED
from app.ml.datasets import time_split
from app.ml.evaluation import multiclass_metrics
from app.ml.features import load_incidents
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput

RBF_SAMPLE = 1500


def _tfidf():
    return TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000, sublinear_tf=True, stop_words="english")


def train(db: Session) -> TaskOutput:
    df = load_incidents(db)
    df = df[df["text"].str.len() > 10]
    split = time_split(df, "created_at")
    X_tr, X_te = split.train["text"], split.test["text"]
    y_tr, y_te = split.train["category"], split.test["category"]
    labels = sorted(df["category"].unique())
    results = []

    nb = Pipeline([("tfidf", _tfidf()), ("model", MultinomialNB(alpha=0.3))]).fit(X_tr, y_tr)
    m, d = multiclass_metrics(y_te, nb.predict(X_te), labels)
    results.append(RunResult("naive_bayes", nb, m, {"alpha": 0.3, "ngrams": "1-2"}, d, score=m["macro_f1"]))

    svm = Pipeline([("tfidf", _tfidf()), ("model", CalibratedClassifierCV(LinearSVC(C=0.5, random_state=SEED), cv=3))]).fit(X_tr, y_tr)
    m, d = multiclass_metrics(y_te, svm.predict(X_te), labels)
    d["top_terms"] = _top_terms(Pipeline([("tfidf", _tfidf()), ("model", LinearSVC(C=0.5, random_state=SEED))]).fit(X_tr, y_tr))
    # Team routing: same text, a second linear SVM predicting the team that resolved similar incidents
    teams = split.train["assigned_team"].fillna("")
    team_model = None
    if (teams != "").sum() > 50:
        mask = teams != ""
        team_model = Pipeline([("tfidf", _tfidf()), ("model", CalibratedClassifierCV(LinearSVC(C=0.5, random_state=SEED), cv=3))])
        team_model.fit(X_tr[mask], teams[mask])
        te_mask = split.test["assigned_team"].fillna("") != ""
        team_acc = float(np.mean(team_model.predict(X_te[te_mask]) == split.test["assigned_team"][te_mask])) if te_mask.any() else None
        m["team_accuracy"] = round(team_acc, 3) if team_acc is not None else None
    results.append(RunResult("linear_svm", {"category": svm, "team": team_model}, m, {"C": 0.5, "ngrams": "1-2"}, d, score=m["macro_f1"]))

    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(X_tr), size=min(RBF_SAMPLE, len(X_tr)), replace=False)
    rbf = Pipeline([("tfidf", _tfidf()), ("model", SVC(kernel="rbf", C=5, gamma="scale", random_state=SEED))])
    rbf.fit(X_tr.iloc[idx], y_tr.iloc[idx])
    m, d = multiclass_metrics(y_te, rbf.predict(X_te), labels)
    results.append(RunResult("rbf_svm", None, m, {"C": 5, "train_sample": int(len(idx))}, d, score=m["macro_f1"] - 1))  # never the active model (no probabilities)
    return TaskOutput(results, split.periods, len(split.train), len(split.test))


def _top_terms(pipe, n: int = 6) -> dict:
    vocab = np.array(pipe.named_steps["tfidf"].get_feature_names_out())
    model = pipe.named_steps["model"]
    return {cls: vocab[np.argsort(-coef)[:n]].tolist() for cls, coef in zip(model.classes_, model.coef_)}
