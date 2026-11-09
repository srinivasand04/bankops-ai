"""Task 5 - Similar incidents (K-Nearest Neighbours) with pgvector.

Each incident's text becomes a 64-number vector (TF-IDF reduced with Truncated SVD, i.e. latent
semantic analysis - a lightweight alternative to a sentence-transformer model). Incidents with similar
wording point in similar directions, so "similar incidents" are the k vectors with the smallest cosine
distance. The vectors are stored in PostgreSQL with pgvector, which does the nearest-neighbour search.
As a comparison point, a KNN classifier predicts the category from the 7 nearest past incidents.
"""

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml import SEED
from app.ml.datasets import time_split
from app.ml.evaluation import multiclass_metrics
from app.ml.features import load_incidents
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput

DIM = 64
K = 7


def embedder() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000, sublinear_tf=True, stop_words="english")),
        ("svd", TruncatedSVD(n_components=DIM, random_state=SEED)),
        ("norm", Normalizer()),
    ])


def to_pgvector(v) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def train(db: Session) -> TaskOutput:
    df = load_incidents(db)
    df = df[df["text"].str.len() > 10]
    split = time_split(df, "created_at")
    emb = embedder().fit(split.train["text"])
    knn = KNeighborsClassifier(n_neighbors=K, metric="cosine", weights="distance")
    knn.fit(emb.transform(split.train["text"]), split.train["category"])
    labels = sorted(df["category"].unique())
    m, d = multiclass_metrics(split.test["category"], knn.predict(emb.transform(split.test["text"])), labels)
    explained = float(emb.named_steps["svd"].explained_variance_ratio_.sum())
    m["svd_explained_variance"] = round(explained, 3)
    d["note"] = "Vectors for every incident are stored in ml_incident_vectors (pgvector) for similarity search."
    return TaskOutput([RunResult("knn_lsa_pgvector", emb, m, {"dim": DIM, "k": K, "distance": "cosine"}, d, score=m["macro_f1"])],
                      split.periods, len(split.train), len(split.test))


def store_vectors(db: Session, emb: Pipeline, run_id: int, incident_ids: list[int] | None = None) -> int:
    """Embed incidents and upsert their vectors (all of them after training, or the given ones)."""
    df = load_incidents(db, incident_ids)
    if df.empty:
        return 0
    vectors = emb.transform(df["text"])
    rows = [{"id": int(i), "v": to_pgvector(v), "run": run_id} for i, v in zip(df["id"], vectors)]
    db.execute(text(
        "INSERT INTO ml_incident_vectors (incident_id, embedding, model_run_id) VALUES (:id, CAST(:v AS vector), :run) "
        "ON CONFLICT (incident_id) DO UPDATE SET embedding = EXCLUDED.embedding, model_run_id = EXCLUDED.model_run_id"
    ), rows)
    db.commit()
    return len(rows)


def nearest(db: Session, incident_id: int, k: int = 5) -> list[dict]:
    """The k most similar other incidents by cosine distance (pgvector `<=>`)."""
    rows = db.execute(text(
        "SELECT i.id, i.reference_number, i.title, i.status, i.severity, a.code, i.resolution_summary, "
        "       v.embedding <=> q.embedding AS distance "
        "FROM ml_incident_vectors q JOIN ml_incident_vectors v ON v.incident_id <> q.incident_id "
        "JOIN incidents i ON i.id = v.incident_id JOIN applications a ON a.id = i.application_id "
        "WHERE q.incident_id = :id ORDER BY v.embedding <=> q.embedding LIMIT :k"
    ), {"id": incident_id, "k": k}).all()
    return [{"id": r[0], "reference": r[1], "title": r[2], "status": r[3], "severity": r[4], "application": r[5],
             "resolution_summary": r[6], "similarity": round(1 - float(r[7]), 3)} for r in rows]


def nearest_text(emb: Pipeline, query: str, all_vectors: np.ndarray, ids: list[int], k: int) -> list[int]:
    q = emb.transform([query])[0]
    return [ids[i] for i in np.argsort(-(all_vectors @ q))[:k]]
