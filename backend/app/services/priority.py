"""
services/priority.py - THE AI PART: an XGBoost model that decides who should be seen first.

Inputs (one row per waiting patient)
  * current situation : symptoms text -> flags/vitals (services/triage.py), age, "emergency" arrival
  * medical history   : conditions detected in the patient's uploaded documents (services/history.py)
  * real-time waiting : minutes waited so far (recomputed on every queue refresh)
Output
  * priority_score 0-100 (higher = see first).   health_score = the same model with waiting time = 0,
    i.e. the pure "how sick is this patient" part that the UI shows as the "AI Health Score".

Safety properties (enforced at training time with XGBoost monotone constraints):
  waiting longer never lowers priority; adding a danger symptom / a risk condition never lowers priority.

IMPORTANT - honest status of the model: there is no public labelled data for *this* exact feature set, so the shipped
model is trained on synthetic patients whose labels come from a transparent triage-style rule set (`teacher_*` below).
It is a working, explainable decision-support prototype - NOT clinically validated. To use real data, train with
`python -m app.ml.train_priority_model --csv your_labelled_data.csv` (see that file). Clinicians always decide.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from app.config import settings
from app.services.history import HISTORY_KEYS
from app.services.triage import (MODIFIER_KEYS, SYMPTOM_KEYS, SYMPTOM_WEIGHT, extract_symptom_features)

log = logging.getLogger("helix.priority")

# ---------------------------------------------------------------------------------------------- features
FEATURE_NAMES: list[str] = (
    [f"sx_{k}" for k in SYMPTOM_KEYS]
    + [f"mod_{k}" for k in MODIFIER_KEYS]
    + ["duration_days", "temp_c", "hr", "spo2", "sbp", "age"]
    + HISTORY_KEYS
    + ["h_count", "base_urgency", "n_symptoms", "is_emergency", "wait_minutes"]
)
STATIC_NAMES = [n for n in FEATURE_NAMES if n != "wait_minutes"]


def _monotone() -> list[int]:
    out = []
    for n in FEATURE_NAMES:
        if n == "sx_routine" or n == "mod_mild" or n == "spo2":
            out.append(-1)                       # more routine / milder / higher oxygen -> lower priority
        elif n.startswith(("sx_", "mod_", "h_")) or n in ("duration_days", "base_urgency", "n_symptoms", "is_emergency", "wait_minutes"):
            out.append(1)                        # more danger / risk / waiting -> higher priority
        else:
            out.append(0)                        # age, temp, hr, bp: not monotone (U-shaped risk)
    return out


MONOTONE_CONSTRAINTS = _monotone()


def add_derived(f: dict) -> dict:
    """Derived clinical summary features (they make the 'most serious complaint wins' logic easy for trees):
         base_urgency = urgency weight of the most serious complaint (30 if no complaint was understood)
         n_symptoms   = how many complaint categories were detected
         h_count      = how many chronic conditions are on record"""
    active = [SYMPTOM_WEIGHT[k] for k in SYMPTOM_KEYS if f.get(f"sx_{k}")]
    f["base_urgency"] = float(max(active)) if active else UNKNOWN_BASE
    f["n_symptoms"] = float(len(active))
    f["h_count"] = float(sum(1 for k in HISTORY_KEYS if f.get(k)))
    return f


def build_static_features(symptoms: str, age: Optional[int], history_flags: Optional[dict], is_emergency: bool) -> dict:
    """Everything the model needs *except* waiting time. JSON-serialisable (None = unknown)."""
    f = extract_symptom_features(symptoms or "")
    f["age"] = float(age) if age is not None else None
    hist = history_flags or {}
    for k in HISTORY_KEYS:
        f[k] = 1.0 if hist.get(k) else 0.0
    f["is_emergency"] = 1.0 if is_emergency else 0.0
    return add_derived(f)


def to_row(static: dict, wait_minutes: float) -> list[float]:
    row = []
    for n in FEATURE_NAMES:
        v = wait_minutes if n == "wait_minutes" else static.get(n)
        row.append(float("nan") if v is None else float(v))
    return row


# ---------------------------------------------------------------------------------------------- teacher
UNKNOWN_BASE = 30.0
def _v(f: dict, k: str) -> Optional[float]:
    v = f.get(k)
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def teacher_health(f: dict) -> float:
    """Transparent triage-style rules (ESI-inspired). Produces the training labels AND is the fallback
    used if the XGBoost model file is unavailable. 0-100."""
    ws = sorted(((SYMPTOM_WEIGHT[k], k) for k in SYMPTOM_KEYS if _v(f, f"sx_{k}")), reverse=True)
    if ws:
        others = sum(w for w, k in ws[1:] if k != "routine")
        base = ws[0][0] + 0.12 * others
    else:
        base = UNKNOWN_BASE                               # complaint not understood -> moderate-low default (flagged for staff review)
    base = min(base, 100.0)
    s = base
    if _v(f, "mod_severe"):
        s += 8 if base >= 25 else 4
    if _v(f, "mod_sudden") and base >= 40:
        s += 6
    if _v(f, "mod_worsening"):
        s += 5 if base >= 25 else 3
    if _v(f, "mod_mild"):
        s -= 8 if base < 70 else 3
    dur = _v(f, "duration_days") or 0.0
    s += min(dur, 7.0) * 0.8 * min(1.0, max(0.0, (70.0 - base) / 25.0))      # long-running mild problems matter a bit; fades out as base rises
    # vitals
    t, hr, sp, bp = _v(f, "temp_c"), _v(f, "hr"), _v(f, "spo2"), _v(f, "sbp")
    if t is not None:
        s += 14 if t >= 40 else 9 if t >= 39 else 4 if t >= 38 else 12 if t < 35 else 0
    if sp is not None:
        s += 20 if sp < 90 else 9 if sp < 94 else 0
    if hr is not None:
        s += 10 if (hr > 130 or hr < 45) else 5 if hr > 110 else 0
    if bp is not None:
        s += 15 if bp < 90 else 10 if bp > 180 else 0
    # age (scaled so a routine refill for an 80 year old isn't "urgent")
    age = _v(f, "age")
    if age is not None:
        scale = min(1.0, base / 50.0)
        s += scale * (14 if age <= 1 else 9 if age <= 5 else 5 if age <= 12 else 12 if age >= 80 else 7 if age >= 65 else 0)
    # history x current complaint interactions
    h = lambda k: bool(_v(f, k))                                      # noqa: E731
    x = lambda k: bool(_v(f, f"sx_{k}"))                              # noqa: E731
    if h("h_cardiac") and (x("chest_pain") or x("breathing") or x("syncope") or x("palpitations")):
        s += 10
    if h("h_diabetes") and (x("fever") or x("gi") or x("confusion") or x("skin")):
        s += 6
    if h("h_respiratory") and (x("breathing") or x("resp_mild") or x("fever")):
        s += 8
    if h("h_immuno") and (x("fever") or x("resp_mild") or x("gi")):
        s += 9
    if h("h_anticoag") and (x("bleeding_severe") or x("trauma")):
        s += 12
    if h("h_stroke") and (x("neuro_mild") or x("confusion") or x("stroke_signs")):
        s += 8
    if h("h_kidney") and (x("gi") or x("fever") or x("abdominal")):
        s += 5
    if h("h_cancer") and x("fever"):
        s += 8
    if h("h_epilepsy") and x("seizure"):
        s += 3
    if h("h_pregnant") and (x("abdominal") or x("pregnancy_issue") or x("bleeding_severe")):
        s += 8
    if base >= 30:
        s += min(6.0, 1.5 * (_v(f, "h_count") or 0.0))
    if _v(f, "is_emergency"):
        s += 8
    return float(min(100.0, max(0.0, s)))


def teacher_priority(health: float, wait_minutes: float, emergency: bool = False) -> float:
    """Health + a saturating waiting-time bonus (max +25, smaller for already-critical patients)."""
    bonus = 25.0 * (1.0 - math.exp(-max(wait_minutes, 0.0) / 60.0)) * max(0.0, 1.0 - health / 130.0)
    return float(min(100.0, max(0.0, health + bonus)))


# ---------------------------------------------------------------------------------------------- model wrapper
class PriorityModel:
    MODEL_FILE = "priority_xgb.json"
    META_FILE = "priority_meta.json"

    def __init__(self) -> None:
        self.booster = None
        self.meta: dict = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.booster is not None

    def load(self, directory: Optional[Path] = None) -> bool:
        directory = directory or settings.MODEL_DIR
        path, meta_path = directory / self.MODEL_FILE, directory / self.META_FILE
        if not path.exists():
            log.warning("No trained priority model at %s - using the rule-based fallback (train one with "
                        "`python -m app.ml.train_priority_model`).", path)
            return False
        try:
            import xgboost as xgb
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            if meta.get("feature_names") != FEATURE_NAMES:
                log.warning("Model feature list does not match the code (retrain the model) - using fallback rules.")
                return False
            booster = xgb.Booster()
            booster.load_model(str(path))
            booster.set_param({"nthread": 1})
            self.booster, self.meta = booster, meta
            log.info("Loaded XGBoost priority model v%s (RMSE %.2f)", meta.get("version"), meta.get("metrics", {}).get("rmse", float("nan")))
            return True
        except Exception as exc:                                       # xgboost missing / corrupt file
            log.warning("Could not load XGBoost model (%s) - using rule-based fallback.", exc)
            self.booster = None
            return False

    # -------- inference
    def predict_rows(self, rows: Sequence[Sequence[float]]) -> np.ndarray:
        arr = np.asarray(rows, dtype=np.float32).reshape(-1, len(FEATURE_NAMES))
        if self.booster is None:
            return np.array([self._fallback(r) for r in arr], dtype=np.float32)
        import xgboost as xgb
        dm = xgb.DMatrix(arr, feature_names=FEATURE_NAMES, missing=np.nan)
        with self._lock:
            out = self.booster.predict(dm)
        return np.clip(out, 0.0, 100.0)

    @staticmethod
    def _fallback(row: np.ndarray) -> float:
        f = {n: (None if math.isnan(v) else float(v)) for n, v in zip(FEATURE_NAMES, row)}
        return teacher_priority(teacher_health(f), f["wait_minutes"] or 0.0)

    def priority(self, items: Sequence[tuple[dict, float]]) -> list[float]:
        """[(static_features, wait_minutes)] -> [priority 0-100]"""
        if not items:
            return []
        out = self.predict_rows([to_row(s, w) for s, w in items])
        return [round(float(x), 1) for x in out]

    def health(self, static: dict) -> float:
        return self.priority([(static, 0.0)])[0]

    @property
    def info(self) -> dict:
        return {"engine": "xgboost" if self.available else "rule-based-fallback",
                "version": self.meta.get("version"), "trainedOn": self.meta.get("label_source"),
                "metrics": self.meta.get("metrics"), "clinicallyValidated": False}


model = PriorityModel()
