from __future__ import annotations

import hashlib
import itertools
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction import FeatureHasher

HASHER = FeatureHasher(n_features=2 ** 18, input_type="dict", dtype=np.float32, alternate_sign=False)
SCHEMA_VERSION = 1


def features(blue, red, region, queue, patch):
    """Only revealed champion IDs and supplied roles enter the feature map."""
    out = defaultdict(float)
    out[f"region:{region}"] = 1
    out[f"queue:{queue}"] = 1
    if patch:
        out[f"patch:{patch}"] = 1
    out[f"known:blue:{len(blue)}"] = 1
    out[f"known:red:{len(red)}"] = 1
    for team, sign in ((blue, 1), (red, -1)):
        ids = sorted(c for c, _ in team)
        for champion, role in team:
            out[f"champion:{champion}"] += sign
            if patch:
                out[f"champion_patch:{patch}:{champion}"] += sign
            if role:
                out[f"role:{role}:{champion}"] += sign
        for pair in itertools.combinations(ids, 2):
            out["synergy:" + ":".join(map(str, pair))] += sign
        for triple in itertools.combinations(ids, 3):
            out["composition:" + ":".join(map(str, triple))] += sign
    for a, _ in blue:
        for b, _ in red:
            lo, hi = sorted((a, b))
            out[f"matchup:{lo}:{hi}"] += 1 if a == lo else -1
    return dict(out)


def team(match, color):
    return [(p["champion_id"], p["role"]) for p in match[color]]


def rng_for(match_id, seed=0):
    return np.random.default_rng(int.from_bytes(hashlib.sha256(f"{seed}:{match_id}".encode()).digest()[:8], "big"))


def masked(match, total=None, sample=0):
    rng = rng_for(match["match_id"], sample)
    if total is None:
        nb, nr = map(int, rng.integers(0, 6, size=2))
    else:
        nb = int(rng.integers(max(0, total - 5), min(5, total) + 1))
        nr = total - nb
    def select(color, n):
        values = team(match, color)
        # Roles are often not visible before final assignment. Random omission trains both cases.
        return [(values[i][0], values[i][1] if rng.random() > .5 else "")
                for i in sorted(rng.choice(5, size=n, replace=False))]
    return select("blue", nb), select("red", nr)
