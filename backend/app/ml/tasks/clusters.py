"""Task 6 - Incident pattern discovery with K-Means (unsupervised).

K-Means places k centre points and assigns every incident to the nearest one, moving the centres until
they settle - grouping incidents with similar wording without being told any labels. We do not know k
in advance, so we try k = 4..16 and read two curves: inertia (total distance to centres; look for the
"elbow" where adding clusters stops helping) and silhouette (how much closer each incident is to its own
cluster than to the next one; higher is better). Each cluster is named by its most characteristic terms
and compared with the known categories and applications to see whether it rediscovers recurring problems.
"""

from collections import Counter

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sqlalchemy.orm import Session

from app.ml import SEED
from app.ml.datasets import time_split
from app.ml.features import load_incidents
from app.ml.registry import RunResult
from app.ml.tasks import TaskOutput
from app.ml.tasks.similar import embedder

K_RANGE = range(4, 17)
SILHOUETTE_SAMPLE = 2000


def train(db: Session) -> TaskOutput:
    df = load_incidents(db)
    df = df[df["text"].str.len() > 10].reset_index(drop=True)
    split = time_split(df, "created_at")  # periods only; clustering uses all incidents (no labels involved)
    emb = embedder().fit(df["text"])
    X = emb.transform(df["text"])
    rng = np.random.default_rng(SEED)
    sample = rng.choice(len(X), size=min(SILHOUETTE_SAMPLE, len(X)), replace=False)
    curve, models = [], {}
    for k in K_RANGE:
        km = KMeans(n_clusters=k, n_init=5, random_state=SEED).fit(X)
        sil = float(silhouette_score(X[sample], km.labels_[sample], metric="cosine"))
        curve.append({"k": k, "inertia": round(float(km.inertia_), 2), "silhouette": round(sil, 3)})
        models[k] = km
    best_k = max(curve, key=lambda c: c["silhouette"])["k"]
    km = models[best_k]
    df["cluster"] = km.labels_

    tfidf = emb.named_steps["tfidf"]
    vocab = np.array(tfidf.get_feature_names_out())
    weights = tfidf.transform(df["text"])
    clusters, purity_hits = [], 0
    for c in range(best_k):
        members = df[df["cluster"] == c]
        mean = np.asarray(weights[members.index].mean(axis=0)).ravel()
        cats, apps = Counter(members["category"]), Counter(members["app"])
        top_cat, top_cat_n = cats.most_common(1)[0]
        purity_hits += top_cat_n
        clusters.append({
            "cluster": c, "size": int(len(members)), "top_terms": vocab[np.argsort(-mean)[:6]].tolist(),
            "main_category": top_cat, "category_share": round(top_cat_n / len(members), 3),
            "main_applications": [a for a, _ in apps.most_common(3)],
            "examples": members["reference"].head(4).tolist(),
        })
    clusters.sort(key=lambda c: -c["size"])
    purity = purity_hits / len(df)
    metrics = {"k": best_k, "silhouette": next(c["silhouette"] for c in curve if c["k"] == best_k),
               "purity_vs_category": round(purity, 3)}
    details = {"elbow": curve, "clusters": clusters,
               "reading": "Purity = share of incidents whose cluster's most common category matches their own. "
                          "High purity with tight top terms means the clusters rediscover real recurring problems."}
    return TaskOutput([RunResult("kmeans", {"embedder": emb, "kmeans": km}, metrics, {"k_range": "4-16", "n_init": 5},
                                 details, score=metrics["silhouette"])],
                      split.periods, len(df), 0)
