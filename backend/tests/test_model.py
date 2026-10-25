"""Guards for the AI model itself (these would have caught the problems found while building it)."""
import numpy as np

from app.ml.synth import sample_profile
from app.services.priority import (FEATURE_NAMES, MONOTONE_CONSTRAINTS, add_derived, build_static_features, model,
                                   teacher_health, teacher_priority)


def test_trained_xgboost_model_is_loaded_not_the_fallback():
    # if the model file is missing / incompatible the app silently falls back to the rules - make CI scream instead
    assert model.available and model.info["engine"] == "xgboost"
    assert model.meta["feature_names"] == FEATURE_NAMES
    assert model.meta["metrics"]["rmse"] < 6 and model.meta["metrics"]["r2"] > 0.9


def test_sensible_scores_for_typical_patients():
    s = lambda text, age, hist=None, emg=False: model.health(build_static_features(text, age, hist or {}, emg))   # noqa: E731
    assert s("severe chest pain radiating to left arm and difficulty breathing", 62) >= 85
    assert s("my baby is unconscious and not breathing", 1) >= 95
    assert 35 <= s("high fever 39.4C and severe headache", 41) <= 85
    assert s("Follow-up checkup", 30) < 25 and s("mild cough", 30) < 30
    assert s("chest tightness", 60, {"h_cardiac": 1}) > s("chest tightness", 60)            # history raises it
    assert s("mild cough", 30, {"h_immuno": 1}) > s("mild cough", 30)


def test_waiting_longer_never_lowers_priority():
    rng = np.random.default_rng(1)
    for _ in range(150):
        f = sample_profile(rng, enriched=bool(rng.random() < .5))
        p = model.priority([(f, w) for w in (0, 15, 30, 60, 120, 240, 480)])
        assert all(b >= a - 0.11 for a, b in zip(p, p[1:])), (p, f)


def test_waiting_cannot_make_a_routine_patient_outrank_a_new_critical_one():
    routine = model.priority([(build_static_features("Follow-up checkup", 28, {}, False), 360)])[0]
    critical = model.priority([(build_static_features("severe chest pain and difficulty breathing", 60, {}, True), 0)])[0]
    assert critical > routine + 40


def test_trained_model_respects_monotone_safety_constraints():
    rng = np.random.default_rng(3)
    safe = [n for n in FEATURE_NAMES if n.startswith(("sx_", "h_", "mod_severe", "mod_sudden", "mod_worsening")) and n not in ("sx_routine", "h_count")]
    for _ in range(150):
        f = sample_profile(rng, enriched=bool(rng.random() < .5))
        w = float(rng.uniform(0, 200))
        base = model.priority([(f, w)])[0]
        for k in safe:
            if f.get(k) == 0.0:
                g = dict(f); g[k] = 1.0; add_derived(g)
                assert model.priority([(g, w)])[0] >= base - 0.11, k          # adding a danger sign / risk factor never lowers it


def test_rule_teacher_is_monotone_adding_a_symptom_never_lowers_the_score():
    """Regression: an 'unrecognised complaint' used to score HIGHER (30) than a recognised cough (24)."""
    rng = np.random.default_rng(5)
    flags = [n for n in FEATURE_NAMES if n.startswith(("sx_", "h_", "mod_severe", "mod_sudden", "mod_worsening")) and n not in ("sx_routine", "h_count")]
    for _ in range(300):
        f = sample_profile(rng, enriched=bool(rng.random() < .3))
        base = teacher_priority(teacher_health(f), 30)
        for k in flags:
            if f.get(k) == 0.0:
                g = dict(f); g[k] = 1.0; add_derived(g)
                assert teacher_priority(teacher_health(g), 30) >= base - 1e-9, k


def test_unrecognised_complaint_gets_a_moderate_default_not_zero():
    unknown = model.health(build_static_features("nothing recognisable here xyz", 30, {}, False))
    assert 15 <= unknown <= 45
