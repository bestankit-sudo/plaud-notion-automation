"""Speaker identification — map anonymous diarization labels to real names.

Two pieces:
  * identify_speakers: match a recording's per-speaker embeddings against the
    voiceprint library (runtime naming).
  * greedy_cluster: cosine clustering used for back-catalog enrollment, where the
    recurring cluster (present in the most recordings) is the device owner ("you").
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .diarize import DiarizationResult
from .voiceprints import VoiceprintStore, cosine


def identify_speakers(
    result: DiarizationResult, store: VoiceprintStore, *, threshold: float = 0.5
) -> dict[str, str | None]:
    """{anonymous_label -> real name or None if unknown}."""
    out: dict[str, str | None] = {}
    for label, emb in result.embeddings.items():
        name, _score = store.match(emb, threshold=threshold)
        out[label] = name
    return out


@dataclass
class Cluster:
    centroid: np.ndarray
    members: list[tuple[str, str]] = field(default_factory=list)  # (recording_id, label)

    @property
    def recordings(self) -> set[str]:
        return {rid for rid, _ in self.members}


def assign_names(
    clusters: list["Cluster"],
    explicit: dict[int, str],
    *,
    auto_handle_min: int | None = None,
) -> dict[int, str]:
    """Map cluster index -> display name. Explicit names first, then optional
    stable handles (Speaker A, B, ...) for still-unnamed recurring clusters.
    Must stay in sync with how voiceprints were enrolled (tag_clusters.py)."""
    names = dict(explicit)
    if auto_handle_min is not None:
        letter = ord("A")
        for idx, c in enumerate(clusters):
            if idx in names or len(c.recordings) < auto_handle_min:
                continue
            names[idx] = f"Speaker {chr(letter)}"
            letter += 1
    return names


def _norm(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def cluster_embeddings(
    items: list[tuple[str, str, list[float]]],
    *,
    threshold: float = 0.55,
    linkage: str = "complete",
) -> list[Cluster]:
    """Agglomerative clustering of per-speaker embeddings on cosine distance.

    Complete linkage means no two voices in a cluster are more than `threshold`
    apart — so distinct people are never merged (the failure mode of the old
    greedy pass). Returns clusters sorted by distinct-recording count.
    """
    from collections import defaultdict

    from sklearn.cluster import AgglomerativeClustering

    if not items:
        return []
    if len(items) == 1:
        rid, label, emb = items[0]
        return [Cluster(centroid=_norm(np.asarray(emb, dtype=np.float32)), members=[(rid, label)])]

    vecs = np.stack([_norm(np.asarray(e, dtype=np.float32)) for _, _, e in items])
    dist = np.clip(1.0 - vecs @ vecs.T, 0.0, 2.0)
    labels = AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric="precomputed", linkage=linkage
    ).fit_predict(dist)

    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[int(lab)].append(i)

    clusters: list[Cluster] = []
    for idxs in groups.values():
        centroid = _norm(vecs[idxs].mean(axis=0))
        members = [(items[i][0], items[i][1]) for i in idxs]
        clusters.append(Cluster(centroid=centroid, members=members))
    clusters.sort(key=lambda c: len(c.recordings), reverse=True)
    return clusters


# Backwards-compatible alias (now agglomerative under the hood).
def greedy_cluster(
    items: list[tuple[str, str, list[float]]], *, threshold: float = 0.55
) -> list[Cluster]:
    return cluster_embeddings(items, threshold=threshold)
