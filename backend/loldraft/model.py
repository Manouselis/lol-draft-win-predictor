from __future__ import annotations

import hashlib
import itertools
import json
import math
import warnings
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import sklearn
from scipy.sparse import vstack
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from .config import cutoff_ts, now_ts
from .features import HASHER, SCHEMA_VERSION, features, masked, team
from .locking import exclusive


def wilson(wins, n):
    if not n:
        return [0.0, 1.0]
    z = 1.95996398454
    p = wins / n
    denom = 1 + z * z / n
    middle = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, middle - half), min(1.0, middle + half)]


def metrics(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    bins = []
    for lower in np.arange(0, 1, .1):
        mask = (p >= lower) & (p < lower + .1 + (1e-9 if lower > .89 else 0))
        n = int(mask.sum())
        if n:
            bins.append({"lower": round(float(lower), 1), "upper": round(float(lower + .1), 1),
                         "count": n, "predicted": float(p[mask].mean()), "observed": float(y[mask].mean()),
                         "interval": wilson(int(y[mask].sum()), n)})
    ece = sum(b["count"] * abs(b["predicted"] - b["observed"]) for b in bins) / max(1, len(y))
    return {"brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "ece": ece, "matches": len(y), "calibration": bins}


def allowed_features(values, supported):
    return {k: v for k, v in values.items() if k in supported or k.startswith("known:")}


def matrix(matches, supported, *, augment=False, total=None):
    chunks, ys, weights = [], [], []
    newest = max(m["started_at"] for m in matches)
    for start in range(0, len(matches), 512):
        rows = []
        for match in matches[start:start + 512]:
            count = 8 if augment else 1
            for sample in range(count):
                reveal = (0 if sample == 0 else 10 if sample == 1 else None) if augment else total
                blue, red = masked(match, total=reveal, sample=sample + 42)
                rows.append(allowed_features(features(blue, red, match["region"], match["queue"], match["patch"]), supported))
                ys.append(int(match["blue_win"]))
                # Eight masks still contribute one match's total weight, not eight independent outcomes.
                weights.append(2 ** (-(newest - match["started_at"]) / (7 * 86400)) / count)
        chunks.append(HASHER.transform(rows))
    return vstack(chunks, format="csr"), np.asarray(ys), np.asarray(weights)


def train(store, settings, *, minimum=50000, progress=None):
    progress = progress or (lambda _: None)
    with exclusive(store.directory / "training.lock"):
        progress("Loading only recent real matches and separating chronological cohorts")
        # A one-day safety margin keeps the model inside the rolling window for at least a day.
        matches = [m for m in store.recent(settings.region, settings.queue, settings.patches)
                   if m["started_at"] >= cutoff_ts() + 86400]
        if len(matches) < minimum:
            raise ValueError(f"Model not ready: need {minimum:,} unique matches within the last 29 days; have {len(matches):,}.")
        a, b = int(len(matches) * .6), int(len(matches) * .8)
        split_a, split_b = matches[a]["started_at"], matches[b]["started_at"]
        fit = [m for m in matches if m["started_at"] < split_a]
        calibration = [m for m in matches if split_a <= m["started_at"] < split_b]
        test = [m for m in matches if m["started_at"] >= split_b]
        if min(map(len, (fit, calibration, test))) < max(30, minimum // 10):
            raise ValueError("Not enough temporally separated matches; collect more distinct match dates")
        if any(len({m["blue_win"] for m in group}) < 2 for group in (fit, calibration, test)):
            raise ValueError("Each chronological cohort must contain both outcomes")
        support = Counter()
        champion_support = Counter()
        pairs = {}
        for m in fit:
            blue, red = team(m, "blue"), team(m, "red")
            support.update(features(blue, red, m["region"], m["queue"], m["patch"]).keys())
            champion_support.update(c for c, _ in blue + red)
            for color, outcome in (("blue", m["blue_win"]), ("red", not m["blue_win"])):
                for combo in itertools.combinations(sorted(p["champion_id"] for p in m[color]), 2):
                    key = "synergy:" + ":".join(map(str, combo))
                    wins, count = pairs.get(key, [0, 0])
                    pairs[key] = [wins + int(outcome), count + 1]
            for x, _ in blue:
                for y, _ in red:
                    lo, hi = sorted((x, y))
                    key = f"matchup:{lo}:{hi}"
                    wins, count = pairs.get(key, [0, 0])
                    lo_win = m["blue_win"] if x == lo else not m["blue_win"]
                    pairs[key] = [wins + int(lo_win), count + 1]
        supported = {k for k, n in support.items() if n >= 20}
        progress(f"Fitting regularized logistic regression on {len(fit):,} matches with masked drafts")
        x, y, weights = matrix(fit, supported, augment=True)
        estimator = LogisticRegression(C=.1, solver="liblinear", max_iter=300, random_state=42)
        with warnings.catch_warnings(record=True) as fit_warnings:
            warnings.simplefilter("always", ConvergenceWarning)
            estimator.fit(x, y, sample_weight=weights)
            if any(issubclass(w.category, ConvergenceWarning) for w in fit_warnings):
                raise ValueError("Model did not converge; no artifact published")
        baseline = float(np.average([m["blue_win"] for m in fit],
                                    weights=[2 ** (-(fit[-1]["started_at"] - m["started_at"]) / (7 * 86400)) for m in fit]))
        del x, y, weights
        progress("Calibrating on a later cohort; the final test cohort stays untouched")
        xcal, ycal, wcal = matrix(calibration, supported, augment=True)
        logits = estimator.decision_function(xcal).reshape(-1, 1)
        calibrator = LogisticRegression(C=1, solver="lbfgs", max_iter=500, random_state=42)
        calibrator.fit(logits, ycal, sample_weight=wcal)
        del xcal, logits
        report = {"groups": {}, "split": {"training": len(fit), "calibration": len(calibration), "test": len(test)},
                  "boundaries": {"train_end_exclusive": split_a, "calibration_end_exclusive": split_b},
                  "baseline_blue_win_rate": baseline, "unique_matches": len(matches),
                  "sample_weight_half_life_days": 7, "training_masks_per_match": 8,
                  "method": "L2 logistic regression + chronological sigmoid calibration"}
        for total in (0, 2, 4, 6, 8, 10):
            progress(f"Evaluating {total}/10 visible champions on {len(test):,} held-out matches")
            xt, yt, _ = matrix(test, supported, total=total)
            probs = (np.full(len(yt), baseline) if total == 0 else
                     calibrator.predict_proba(estimator.decision_function(xt).reshape(-1, 1))[:, 1])
            report["groups"][str(total)] = {"model": metrics(yt, probs),
                                            "baseline": metrics(yt, np.full(len(yt), baseline))}
        report["validation_warning"] = any(
            group["model"]["brier"] > group["baseline"]["brier"] + .002
            for key, group in report["groups"].items() if key != "0"
        )
        version = hashlib.sha256((str(now_ts()) + ":" + ":".join(m["match_id"] for m in matches)).encode()).hexdigest()[:12]
        patch_weights = Counter()
        patch_wins = Counter()
        for match in fit:
            weight = 2 ** (-(fit[-1]["started_at"] - match["started_at"]) / (7 * 86400))
            patch_weights[match["patch"]] += weight
            patch_wins[match["patch"]] += weight * int(match["blue_win"])
        metadata = {"version": version, "schema": SCHEMA_VERSION, "sklearn": sklearn.__version__,
                    "trained_at": now_ts(), "oldest": matches[0]["started_at"],
                    "expires_at": matches[0]["started_at"] + 30 * 86400,
                    "newest": matches[-1]["started_at"], "matches": len(matches),
                    "region": settings.region, "queue": settings.queue,
                    "patches": dict(Counter(m["patch"] for m in fit)),
                    "dataset_patches": dict(Counter(m["patch"] for m in matches)),
                    "patch_weights": dict(patch_weights), "synthetic": False,
                    "report": report}
        artifact = {"metadata": metadata, "estimator": estimator, "calibrator": calibrator,
                    "supported": supported, "champion_support": dict(champion_support),
                    "pairs": pairs, "baseline": baseline,
                    "patch_baselines": {p: patch_wins[p] / w for p, w in patch_weights.items()}}
        # Only load artifacts produced locally by this application. joblib is not an import format.
        target = store.directory / "model.joblib"
        temp = target.with_suffix(".tmp")
        joblib.dump(artifact, temp, compress=3)
        temp.replace(target)
        (store.directory / "evaluation.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        store.set_meta("model", metadata)
        progress("Model saved. Review held-out performance and calibration before interpreting estimates.")
        return metadata


class Predictor:
    def __init__(self, directory: Path):
        self.path = directory / "model.joblib"
        self.artifact = None
        self.stamp = None
        self.load_error = None

    def reload(self):
        stamp = self.path.stat().st_mtime_ns if self.path.exists() else None
        if stamp == self.stamp:
            return
        self.stamp = stamp
        self.artifact = None
        if stamp is None:
            return
        try:
            artifact = joblib.load(self.path)
            meta = artifact["metadata"]
            if meta["schema"] != SCHEMA_VERSION or meta["sklearn"] != sklearn.__version__:
                raise ValueError("Incompatible model version; retrain locally")
            if meta.get("synthetic"):
                raise ValueError("Synthetic models cannot serve real predictions")
            self.artifact = artifact
            self.load_error = None
        except Exception:
            self.load_error = "Model file is invalid or incompatible; retrain locally"

    def predict(self, draft, include_hovers=True):
        self.reload()
        unavailable = {"ready": False, "probability": None, "interval": None,
                       "reason": self.load_error or "Model not ready — collect recent historical matches, then train."}
        if not self.artifact:
            return unavailable
        a = self.artifact
        meta = a["metadata"]
        if now_ts() > meta["expires_at"]:
            return {**unavailable, "reason": "Model expired: training includes matches now older than 30 days. Refresh and retrain."}
        if draft.region != meta["region"] or draft.queue != meta["queue"]:
            return {**unavailable, "reason": "Region or queue differs from this model. Train on the selected dataset."}
        if draft.patch and draft.patch not in meta["patches"]:
            return {**unavailable, "reason": "Selected patch has no training coverage. Collect matches on that patch."}
        blue, red = draft.teams(include_hovers)
        ids = [c for c, _ in blue + red]
        if len(ids) != len(set(ids)):
            return {**unavailable, "reason": "Tentative hovers conflict. Confirmed picks are evaluated separately."}
        rare = [c for c in ids if a["champion_support"].get(c, 0) < 20]
        if rare:
            return {**unavailable, "reason": "Insufficient recent historical support for visible champion IDs: " + ", ".join(map(str, rare))}
        def probability(b, r):
            if not b and not r:
                return a["patch_baselines"].get(draft.patch, a["baseline"])
            # Unknown patch means a recency-weighted mixture of covered patches, never an invented patch.
            patches = {draft.patch: 1} if draft.patch else meta["patch_weights"]
            rows = [allowed_features(features(b, r, draft.region, draft.queue, patch), a["supported"])
                    for patch in patches]
            logits = a["estimator"].decision_function(HASHER.transform(rows)).reshape(-1, 1)
            probs = a["calibrator"].predict_proba(logits)[:, 1]
            return float(np.average(probs, weights=list(patches.values())))
        pblue = probability(blue, red)
        p = 1 - pblue if draft.side == "red" else pblue
        if draft.side == "unknown":
            p = (pblue + 1 - probability(red, blue)) / 2
        total = len(ids)
        group_key = str(min((0, 2, 4, 6, 8, 10), key=lambda n: abs(n - total)))
        group = meta["report"]["groups"][group_key]["model"]
        bucket = next((b for b in group["calibration"] if b["lower"] <= pblue <= b["upper"]), None)
        interval = bucket["interval"] if bucket else None
        if interval and draft.side == "red":
            interval = [1 - interval[1], 1 - interval[0]]
        if draft.side == "unknown":
            interval = None  # No validated interval for the equal-side mixture.
        effects = []
        for color, picks in (("blue", blue), ("red", red)):
            for index, (champion, _) in enumerate(picks):
                without = picks[:index] + picks[index + 1:]
                removed = probability(without, red) if color == "blue" else probability(blue, without)
                effect = (pblue - removed) * (1 if draft.side != "red" else -1)
                if draft.side != "unknown":
                    effects.append({"champion_id": champion, "change": effect,
                                    "training_matches": a["champion_support"][champion]})
        stats = []
        for picks in (blue, red):
            for combo in itertools.combinations(sorted(c for c, _ in picks), 2):
                key = "synergy:" + ":".join(map(str, combo))
                wins, n = a["pairs"].get(key, [0, 0])
                if n >= 100:
                    stats.append({"kind": "synergy", "champions": list(combo), "wins": wins,
                                  "matches": n, "win_rate": wins / n, "interval": wilson(wins, n)})
        for x, _ in blue:
            for y, _ in red:
                lo, hi = sorted((x, y))
                wins, n = a["pairs"].get(f"matchup:{lo}:{hi}", [0, 0])
                if n >= 100:
                    stats.append({"kind": "matchup", "champions": [lo, hi], "wins": wins,
                                  "matches": n, "win_rate": wins / n, "interval": wilson(wins, n)})
        return {"ready": True, "probability": p, "interval": interval,
                "interval_label": "95% held-out calibration bin interval; not an individual-match confidence interval",
                "calibration_matches": bucket["count"] if bucket else 0,
                "confidence": "limited" if meta["report"]["validation_warning"] or not bucket or bucket["count"] < 200 else "supported",
                "known": total, "training_matches": meta["report"]["split"]["training"],
                "dataset_matches": meta["matches"], "version": meta["version"],
                "tentative": include_hovers and any(pick.state == "hover" for pick in draft.allies + draft.enemies),
                "baseline": 1 - a["baseline"] if draft.side == "red" else .5 if draft.side == "unknown" else a["baseline"],
                "effects": sorted(effects, key=lambda e: abs(e["change"]), reverse=True)[:4],
                "statistics": sorted(stats, key=lambda s: s["matches"], reverse=True)[:5],
                "validation_warning": meta["report"]["validation_warning"]}
