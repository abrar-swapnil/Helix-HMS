"""
ml/train_priority_model.py - train (or re-train) the XGBoost priority model.

    cd backend
    python -m app.ml.train_priority_model                    # synthetic data (default, ~20 s)
    python -m app.ml.train_priority_model --samples 100000
    python -m app.ml.train_priority_model --csv my_data.csv  # REAL labelled data

CSV format for real data: one row per past patient, a column named `target` (0-100 priority/acuity as judged by
clinicians) plus any of the feature columns listed in services/priority.py::FEATURE_NAMES (missing columns /
empty cells are treated as 'unknown'). `wait_minutes` should be the minutes the patient had waited.

Outputs (read by the app on startup):  app/ml/priority_xgb.json  and  app/ml/priority_meta.json
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.ml.synth import make_dataset
from app.services.priority import FEATURE_NAMES, MONOTONE_CONSTRAINTS, PriorityModel


def load_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rows, ys = [], []
    with path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            ys.append(float(rec["target"]))
            rows.append([float(rec[n]) if rec.get(n) not in (None, "") else float("nan") for n in FEATURE_NAMES])
    return np.asarray(rows, dtype=np.float32), np.asarray(ys, dtype=np.float32)


def train(X: np.ndarray, y: np.ndarray, seed: int = 11, rounds: int = 1500) -> tuple["object", dict]:
    import xgboost as xgb

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    cut = int(len(X) * .85)
    tr, va = idx[:cut], idx[cut:]
    dtr = xgb.DMatrix(X[tr], label=y[tr], feature_names=FEATURE_NAMES, missing=np.nan)
    dva = xgb.DMatrix(X[va], label=y[va], feature_names=FEATURE_NAMES, missing=np.nan)
    params = {
        "objective": "reg:squarederror", "eval_metric": "rmse", "tree_method": "hist",
        "max_depth": 7, "eta": 0.08, "subsample": 0.85, "colsample_bytree": 0.9, "min_child_weight": 3,
        "lambda": 1.0, "seed": seed, "nthread": 2,
        # safety: waiting longer / more danger signs / more risk factors can never LOWER the priority
        "monotone_constraints": "(" + ",".join(str(c) for c in MONOTONE_CONSTRAINTS) + ")",
    }
    booster = xgb.train(params, dtr, num_boost_round=rounds, evals=[(dva, "val")], early_stopping_rounds=40, verbose_eval=False)
    pred = booster.predict(dva, iteration_range=(0, booster.best_iteration + 1))
    err = pred - y[va]
    ss_res, ss_tot = float((err ** 2).sum()), float(((y[va] - y[va].mean()) ** 2).sum())
    metrics = {"rmse": round(float(np.sqrt((err ** 2).mean())), 3), "mae": round(float(np.abs(err).mean()), 3),
               "r2": round(1 - ss_res / ss_tot, 4), "n_train": int(len(tr)), "n_val": int(len(va)), "best_iteration": int(booster.best_iteration)}
    return booster, metrics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=int, default=120000)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()

    t0 = time.time()
    if a.csv:
        X, y = load_csv(a.csv)
        source = f"csv:{a.csv.name}"
    else:
        X, y = make_dataset(a.samples, seed=a.seed)
        source = "synthetic-triage-rules-v1"
    print(f"data: {X.shape[0]} rows x {X.shape[1]} features ({source}) in {time.time()-t0:.1f}s")

    booster, metrics = train(X, y, seed=a.seed)
    import xgboost
    a.out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(a.out / PriorityModel.MODEL_FILE))
    meta = {"version": datetime.now(timezone.utc).strftime("%Y.%m.%d"), "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label_source": source, "xgboost_version": xgboost.__version__, "feature_names": FEATURE_NAMES,
            "monotone_constraints": MONOTONE_CONSTRAINTS, "metrics": metrics,
            "warning": "Trained on synthetic data unless label_source says csv. Decision support only - not clinically validated."}
    (a.out / PriorityModel.META_FILE).write_text(json.dumps(meta, indent=2))
    print("metrics:", metrics)
    print(f"saved -> {a.out / PriorityModel.MODEL_FILE}   (total {time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
