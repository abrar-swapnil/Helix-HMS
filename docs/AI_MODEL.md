# The AI in Helix HMS - what it is, what it is not

Two AI components: the **XGBoost priority model** (orders the queue) and the **Ollama chatbot** (talks to patients).

## 1. XGBoost priority model

**Job:** for every waiting patient, output a *priority score 0-100*. The doctor's waiting list, the receptionist's lists
and the patient's "you are #2 in the queue" are all sorted by it. It is recomputed on every refresh, so it changes as time passes.

**Inputs (49 numbers per patient)** - see `backend/app/services/priority.py::FEATURE_NAMES`

| Group | Examples | Where it comes from |
|---|---|---|
| Current situation | 21 complaint flags (chest pain, breathing, bleeding, fever ...), severity words ("severe", "sudden", "worsening", "mild"), days of symptoms, temperature / heart rate / SpO2 / blood pressure if typed in the text, age, "emergency" arrival | the symptoms text -> `services/triage.py` (negation-aware: "no chest pain" is ignored; "father had a heart attack" is ignored, "my father is unconscious" is not) |
| Medical history | heart disease, hypertension, diabetes, asthma/COPD, stroke, cancer, kidney, liver, immunocompromised, blood thinners, epilepsy, pregnancy, recent surgery | the patient's uploaded documents (PDF text, TXT, or the note typed with an image) -> `services/history.py` |
| Real-time waiting | minutes waited so far | clock: starts at arrival (emergency) or at the scheduled time (general) |

**Output**
* `priorityScore` - condition **and** waiting time (used for ordering)
* `healthScore`  - the same model with waiting time = 0 (shown as the "AI Health Score" badge)

**Safety properties (enforced by XGBoost monotone constraints, and tested)**
* waiting longer never *lowers* priority
* adding a danger sign or a risk condition never *lowers* priority
* waiting adds at most about +25 points and less for already-sick patients, so a long-waiting routine patient never
  overtakes a new critical one (tested: routine after 6 h = ~33, new critical = ~97)

**How good is it? (read this before you present it)**
* The model is trained on **synthetic patients** (`ml/synth.py`) whose labels come from transparent triage-style rules
  (`teacher_health` / `teacher_priority`, loosely modelled on emergency-triage practice). Reason: there is no public dataset with
  this exact combination (free-text symptoms + prior records + waiting time).
* So the honest description is: *"an XGBoost model distilled from a clinical-style rule set, with learned interactions and
  guaranteed monotone behaviour, ready to be retrained on real hospital data."* **It is not clinically validated.**
* Fit to the rules: RMSE about 2.5 points on fresh data versus the noise-free rules (training labels contain +-2.5 noise; validation R² 0.977), and no band is biased by more than about 2 points.
  That measures how well it learned the rules - **not** whether the rules are medically right.
* The UI calls it "AI-assisted estimate - not a diagnosis. Clinicians decide." Keep that wording.
* Limitations: English symptom text only (anything it cannot understand gets a moderate default score and the preview says so);
  scanned PDFs / photos have no text unless a note is typed; vitals are only used if typed inside the symptom text.

**Use real data later** (this is the upgrade path judges like to hear)
```bash
cd backend
# CSV: one row per past patient. Column "target" = priority/acuity 0-100 given by clinicians, plus any of the FEATURE_NAMES columns
python -m app.ml.train_priority_model --csv my_labelled_patients.csv
```
The application code does not change - restart the server and it loads the new `app/ml/priority_xgb.json`.
Re-train with the synthetic data again: `python -m app.ml.train_priority_model` (about 20 seconds).
If the model file is missing/incompatible the app keeps working with the rule set (`/api/ai/status` shows `rule-based-fallback`).

## 2. Ollama chatbot ("Helix AI" / "MediAssist")

* Runs a local LLM through Ollama (`OLLAMA_MODEL`, default `llama3.2`). Answers stream word by word.
* **Grounded in the live database:** before every answer the backend reads the current doctors (name, specialty, department,
  status, patients waiting, estimated wait) and - for a signed-in patient - *their own* upcoming appointments, and puts them in the
  system prompt. Add, edit or remove a doctor anywhere and the chatbot knows on the next message. There is no second copy of the data.
* **Privacy:** signed-out visitors get public facts only. No doctor phone/email, no patient data. A patient sees only their own.
* **Safety:** the prompt forbids diagnosis / medication advice / inventing facts. Separately from the LLM, the backend checks every
  message for emergency wording and *prepends a fixed "call the emergency number" notice* - this does not depend on the model behaving.
* **Fallback:** if Ollama is not running (or the model is not installed) the chatbot switches to "Basic mode": a rule-based
  responder using the same live data. The UI shows "Basic mode - AI model offline" so nobody is misled.
* What is verified: the whole integration against a fake Ollama server that speaks the real protocol (streaming, prompt contents,
  privacy, fallback, mid-stream failure). What is **not** verified here: the quality of a real model's answers - try it on your PC.
