"""
ml/synth.py - synthetic patient generator for training the XGBoost priority model.

Why synthetic?  There is no public dataset with *this* feature set (free-text symptoms + prior records +
waiting time). So we sample realistic patient profiles and label them with the transparent triage rules in
services/priority.py (`teacher_health` / `teacher_priority`) plus noise. XGBoost then learns a smooth function
(including the interactions) that can run in milliseconds - and, unlike the raw rules, is trained with
monotone constraints and can be re-trained on REAL labelled data later without touching the application code.
"""
from __future__ import annotations

import numpy as np

from app.services.history import HISTORY_KEYS
from app.services.priority import FEATURE_NAMES, add_derived, teacher_health, teacher_priority, to_row
from app.services.triage import MODIFIER_KEYS, SYMPTOM_KEYS

# Rough prevalence of each complaint at a hospital front desk: ~12% critical, ~28% urgent, ~60% moderate/routine.
PREVALENCE = {
    "arrest_collapse": .005, "stroke_signs": .008, "allergic_severe": .005, "bleeding_severe": .010, "seizure": .008, "breathing": .030,
    "chest_pain": .030, "mental_crisis": .006, "pregnancy_issue": .010, "confusion": .010, "trauma": .060, "syncope": .030,
    "palpitations": .030, "abdominal": .060, "fever": .100, "neuro_mild": .100, "gi": .120, "pain_general": .110, "skin": .070,
    "resp_mild": .130, "routine": .100,
}
HISTORY_PREV = {"h_cardiac": .10, "h_hypertension": .25, "h_diabetes": .15, "h_respiratory": .08, "h_stroke": .03, "h_cancer": .04,
                "h_kidney": .03, "h_liver": .02, "h_immuno": .03, "h_anticoag": .05, "h_epilepsy": .02, "h_pregnant": .03,
                "h_recent_surgery": .04}


def sample_profile(rng: np.random.Generator, enriched: bool = False) -> dict:
    f: dict = {n: 0.0 for n in FEATURE_NAMES if n.startswith(("sx_", "mod_")) or n in HISTORY_KEYS or n == "is_emergency"}
    f.update(duration_days=0.0, temp_c=None, hr=None, spo2=None, sbp=None, age=None)

    n_cats = rng.choice([0, 1, 2, 3], p=[.04, .62, .28, .06])
    if n_cats:
        p = np.array([1.0 if enriched else PREVALENCE[k] for k in SYMPTOM_KEYS]); p = p / p.sum()   # enriched = every complaint equally likely
        for k in rng.choice(SYMPTOM_KEYS, size=n_cats, replace=False, p=p):
            f[f"sx_{k}"] = 1.0
    f["mod_severe"] = float(rng.random() < (.30 if enriched else .15))
    f["mod_sudden"] = float(rng.random() < .12)
    f["mod_worsening"] = float(rng.random() < .20)
    f["mod_mild"] = float(rng.random() < .25 and not f["mod_severe"])
    if rng.random() < .6:
        f["duration_days"] = float(min(60, rng.geometric(.35)))

    if rng.random() < .25:
        f["temp_c"] = float(np.clip(rng.normal(38.8 if f["sx_fever"] else 37.2, .9), 34, 42))
    if rng.random() < .15:
        f["hr"] = float(np.clip(rng.normal(100 if f["sx_chest_pain"] or f["sx_breathing"] else 82, 18), 30, 190))
    if rng.random() < .12:
        f["spo2"] = float(np.clip(rng.normal(90 if f["sx_breathing"] else 97, 4), 60, 100))
    if rng.random() < .12:
        f["sbp"] = float(np.clip(rng.normal(125, 28), 55, 230))

    r = rng.random()
    age = rng.integers(0, 13) if r < .12 else rng.integers(13, 60) if r < .62 else rng.integers(60, 96)
    f["age"] = float(age)
    af = 0.4 if age < 30 else 1.0 if age < 60 else 2.2
    for k in HISTORY_KEYS:
        f[k] = float(rng.random() < min(.8, HISTORY_PREV[k] * af))
    add_derived(f)
    pre = teacher_health({**f, "is_emergency": 0.0})
    f["is_emergency"] = float(rng.random() < (.6 if pre >= 60 else .06))
    return f


def make_dataset(n: int, seed: int = 7, noise: float = 2.5, enriched_fraction: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    """75% realistic traffic + 25% 'every complaint equally likely' so rare dangerous cases are learned well too."""
    rng = np.random.default_rng(seed)
    X = np.empty((n, len(FEATURE_NAMES)), dtype=np.float32)
    y = np.empty(n, dtype=np.float32)
    for i in range(n):
        f = sample_profile(rng, enriched=rng.random() < enriched_fraction)
        wait = float(np.clip(rng.exponential(45), 0, 360))
        X[i] = to_row(f, wait)
        y[i] = np.clip(teacher_priority(teacher_health(f), wait) + rng.normal(0, noise), 0, 100)
    return X, y
