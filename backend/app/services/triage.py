"""
services/triage.py - turn a patient's free-text complaint into structured clinical features.

This is the *feature extraction* half of the AI triage. The output (a dict of numbers) is fed to the
XGBoost priority model in services/priority.py.

Design notes
  * Deterministic and auditable on purpose: for a safety-relevant ordering you want to be able to say
    exactly which words produced which feature. (An LLM could replace this later - keep the output keys.)
  * Negation aware: "no chest pain", "denies fever" do not count.
  * Pulls simple vitals out of the text when present: temperature, heart rate, SpO2, systolic BP.

>>> TO EXTEND: add a regex to SYMPTOM_PATTERNS (and a feature name in services/priority.py + retrain). <<<
"""
from __future__ import annotations

import re
from typing import Optional

# --------------------------------------------------------------------------- symptom categories
def _rx(*alts: str) -> re.Pattern:
    return re.compile(r"(?:%s)" % "|".join(alts), re.IGNORECASE)


SYMPTOM_PATTERNS: dict[str, re.Pattern] = {
    # ---- life threatening
    "arrest_collapse": _rx(r"\bunconscious(?:ness)?\b", r"\bunresponsive\b", r"\bnot breathing\b", r"\bstopped breathing\b",
                           r"\bcardiac arrest\b", r"\bno pulse\b", r"\bcollapsed?\b", r"\bnot waking\b", r"\bhard to wake\b"),
    "stroke_signs": _rx(r"\bstroke\b", r"\bfac(?:e|ial) droop\w*", r"\bslurred speech\b", r"\bslurring\b",
                        r"\b(?:can'?t|cannot|unable to) speak\b", r"\bsudden (?:weakness|numbness)\b",
                        r"\bone[- ]sided weakness\b", r"\bsudden (?:loss of vision|vision loss)\b", r"\bthunderclap\b"),
    "chest_pain": _rx(r"\bchest (?:pain|pressure|tightness|discomfort|heaviness)\b", r"\btight chest\b", r"\bheart attack\b",
                      r"\bangina\b", r"\bradiating (?:pain )?to (?:the )?(?:left )?(?:arm|jaw|shoulder)\b",
                      r"\bpain (?:spreading|radiating) to (?:the )?(?:left )?(?:arm|jaw|shoulder)\b", r"\bcrushing (?:chest )?pain\b"),
    "breathing": _rx(r"\bshort(?:ness)? of breath\b", r"\b(?:difficulty|trouble|hard to|struggling to|labou?red) breath\w*",
                     r"\bcan'?t breathe\b", r"\bcannot breathe\b", r"\bbreathless\w*", r"\bwheez\w*", r"\bgasping\b",
                     r"\bchoking\b", r"\brespiratory distress\b"),
    "bleeding_severe": _rx(r"\b(?:heavy|severe|profuse|uncontrolled) bleeding\b", r"\bbleeding (?:heavily|profusely|a lot|won'?t stop|will not stop)\b",
                           r"\bvomit\w* (?:up )?blood\b", r"\bcough\w* (?:up )?blood\b", r"\bblood in (?:the )?(?:stool|urine|vomit)\b",
                           r"\bblack (?:tarry )?stools?\b", r"\bh(?:a)?emorrhag\w+", r"\bbleeding from\b"),
    "seizure": _rx(r"\bseizures?\b", r"\bconvulsions?\b", r"\bconvulsing\b", r"\bepileptic fit\b", r"\bfitting\b"),
    "allergic_severe": _rx(r"\banaphyla\w+", r"\bswelling of (?:the )?(?:face|lips|tongue|throat)\b", r"\b(?:face|lip|tongue|throat) (?:is )?swelling\b",
                           r"\bthroat (?:closing|tight)\b"),
    "mental_crisis": _rx(r"\bsuicid\w+", r"\bkill (?:myself|himself|herself)\b", r"\bself[- ]harm\w*", r"\boverdos\w+",
                         r"\bwant(?:s)? to die\b", r"\bend(?:ing)? (?:my|his|her) life\b", r"\bhallucinat\w+"),
    "pregnancy_issue": _rx(r"\bpregnan\w*[^.;]{0,50}\b(?:bleeding|pain|cramp\w*|contraction\w*|leak\w*|water broke|reduced movement)\b",
                           r"\b(?:bleeding|pain|cramp\w*|contraction\w*|water broke)\b[^.;]{0,50}\bpregnan\w*",
                           r"\bin labou?r\b", r"\bwater (?:has )?broken\b", r"\bmiscarriage\b"),
    "confusion": _rx(r"\bconfus\w+", r"\bdisorient\w+", r"\baltered mental\b", r"\bnot making sense\b", r"\bdelirious\b",
                     r"\bunusually sleepy\b", r"\blethargic\b"),
    # ---- urgent
    "trauma": _rx(r"\baccident\b", r"\bcrash\b", r"\bfracture\w*", r"\bbroken (?:bone|arm|leg|rib|wrist|ankle|collarbone|hip|finger|nose|jaw)\b",
                  r"\bhead injury\b", r"\bhit (?:my|his|her) head\b", r"\bstab\w*", r"\bgunshot\b", r"\bburns?\b", r"\bburned\b",
                  r"\bdeep cut\b", r"\blaceration\b", r"\bdislocat\w+", r"\bfell (?:down|off|from)\b", r"\bfall from\b", r"\binjur\w+"),
    "palpitations": _rx(r"\bpalpitations?\b", r"\bheart (?:is )?racing\b", r"\brac(?:ing|e) heart\b", r"\birregular heart ?beat\b", r"\bfluttering\b"),
    "syncope": _rx(r"\bfaint\w*", r"\bpassed out\b", r"\bpassing out\b", r"\bblacked out\b", r"\bsyncope\b"),
    "abdominal": _rx(r"\babdominal (?:pain|cramps?)\b", r"\b(?:stomach|belly|tummy) ?(?:pain|ache)\b", r"\bappendicitis\b",
                     r"\bgallstones?\b", r"\bkidney stones?\b", r"\brenal colic\b", r"\bflank pain\b", r"\bpain in (?:the )?(?:lower )?(?:right )?abdomen\b"),
    "fever": _rx(r"\bfever\w*", r"\bfebrile\b", r"\bhigh temperature\b", r"\bchills\b", r"\bshivering\b"),
    # ---- moderate / routine
    "neuro_mild": _rx(r"\bheadaches?\b", r"\bmigraines?\b", r"\bdizz\w+", r"\bvertigo\b", r"\bnumbness\b", r"\btingling\b",
                      r"\bblurred vision\b", r"\blight-?headed\b"),
    "gi": _rx(r"\bnause\w+", r"\bvomit\w*", r"\bdiarr?h?oea\b", r"\bdiarrhea\b", r"\bconstipation\b", r"\bloose (?:stool|motion)s?\b",
              r"\bgastroenteritis\b", r"\bfood poisoning\b", r"\bindigestion\b", r"\bacid reflux\b", r"\bheartburn\b"),
    "pain_general": _rx(r"\bbody ?(?:pain|ache)s?\b", r"\bjoint (?:pain|ache)s?\b", r"\bback pain\b", r"\bmuscle (?:pain|ache)s?\b",
                        r"\bneck pain\b", r"\b(?:knee|shoulder|hip|elbow|wrist|ankle) pain\b", r"\barthritis\b", r"\bsprain\w*"),
    "skin": _rx(r"\brash(?:es)?\b", r"\bitch\w*", r"\bskin\b", r"\beczema\b", r"\bacne\b", r"\bhives\b", r"\ballerg\w+"),
    "resp_mild": _rx(r"\bcough\w*", r"\b(?:common )?cold\b", r"\bsore throat\b", r"\brunny nose\b", r"\bcongestion\b", r"\bsneez\w+",
                     r"\bflu\b", r"\bsinus\w*", r"\bstuffy nose\b", r"\btonsil\w*"),
    "routine": _rx(r"\bfollow[- ]?up\b", r"\bcheck[- ]?up\b", r"\broutine\b", r"\bprescription\b", r"\brefill\b", r"\brenewal\b",
                   r"\bvaccin\w+", r"\bimmuni[sz]ation\b", r"\bmedical certificate\b", r"\bannual\b", r"\bscreening\b",
                   r"\bsecond opinion\b", r"\blab results?\b", r"\btest results?\b", r"\breview\b", r"\bconsultation\b"),
}

MODIFIER_PATTERNS: dict[str, re.Pattern] = {
    "severe": _rx(r"\bsevere\w*", r"\bintense\w*", r"\bunbearable\b", r"\bexcruciating\b", r"\bcrushing\b", r"\bworst\b", r"\bextreme\w*",
                  r"\bterrible\b", r"\bagoni[sz]ing\b", r"\bvery bad\b", r"\breally bad\b", r"\bunable to (?:move|walk|stand)\b"),
    "sudden": _rx(r"\bsudden\w*", r"\babrupt\w*", r"\bout of nowhere\b", r"\ball of a sudden\b", r"\bjust now\b",
                  r"\bstarted (?:a few |\d+ )?(?:minutes|mins|an hour)\b"),
    "worsening": _rx(r"\bworsen\w*", r"\bgetting worse\b", r"\bgot worse\b", r"\bspreading\b", r"\bincreasing\b", r"\bdeteriorat\w+",
                     r"\bnot improving\b", r"\bpersistent\b", r"\bwon'?t go away\b"),
    "mild": _rx(r"\bmild\w*", r"\bslight\w*", r"\bminor\b", r"\ba little\b", r"\ba bit\b", r"\boccasional\w*", r"\bon and off\b", r"\bmanageable\b"),
}

SYMPTOM_KEYS = list(SYMPTOM_PATTERNS)
MODIFIER_KEYS = list(MODIFIER_PATTERNS)

# --------------------------------------------------------------------------- negation handling
_NEG = re.compile(r"\b(?:no|not|denies|denied|without|never|negative for|free of|absence of|ruled out|isn'?t|doesn'?t|didn'?t|hasn'?t|haven'?t|nil)\b",
                  re.IGNORECASE)
_FAMILY_HIST = re.compile(r"\bfamily history\b|\bruns in (?:the )?family\b", re.IGNORECASE)
_RELATIVE = re.compile(r"\b(?:mother|father|brother|sister|grand\w+|parents?|uncle|aunt|relatives?|cousin)\b", re.IGNORECASE)
_PAST = re.compile(r"\b(?:had|has had|history|died|dies|suffered|passed away|diagnosed|runs)\b", re.IGNORECASE)
# a negation never reaches across these: "no fever. cough" / "no pain but cough" / "no pain, just a cough"
_CLAUSE_BREAK = re.compile(r"[.;:!?\n]|\b(?:but|however|although|except|just|only|though)\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9']+")
NEG_SCOPE_WORDS = 4          # "no chest pain", "denies fever, cough" -> negated; "no chest pain, just a mild cough" -> not
FAMILY_SCOPE_WORDS = 4


def _within_scope(text: str, start: int, cue: re.Pattern, max_words: int, require: Optional[re.Pattern] = None, window: int = 90) -> bool:
    left = text[max(0, start - window):start]
    clause = _CLAUSE_BREAK.split(left)[-1]
    last = None
    for last in cue.finditer(clause):
        pass
    if last is None:
        return False
    between = clause[last.end():]
    if len(_WORD.findall(between)) > max_words:
        return False
    return bool(require.search(between)) if require is not None else True


def negated_or_other_person(text: str, start: int, strict_family: bool = True) -> bool:
    """True if the match at `start` is negated ("no chest pain") or is about a relative's HISTORY.

    strict_family=True  (medical records): ANY mention of a relative excludes it ("mother has diabetes" is not the patient's).
    strict_family=False (current symptoms / chat): only relative + history wording excludes it ("father had a heart attack"),
                        while "my father is unconscious" is a present emergency and MUST still be detected."""
    if _within_scope(text, start, _NEG, NEG_SCOPE_WORDS) or _within_scope(text, start, _FAMILY_HIST, FAMILY_SCOPE_WORDS):
        return True
    if strict_family:
        return _within_scope(text, start, _RELATIVE, FAMILY_SCOPE_WORDS)
    return _within_scope(text, start, _RELATIVE, FAMILY_SCOPE_WORDS, require=_PAST)


def has_unnegated(pattern: re.Pattern, text: str, strict_family: bool = False) -> bool:
    return any(not negated_or_other_person(text, m.start(), strict_family) for m in pattern.finditer(text))


# --------------------------------------------------------------------------- numeric extraction
_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "couple": 2, "few": 3}
_DUR = re.compile(r"\b(?:for|since|past|last|x|over|about|around)?\s*(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple of|few)\s*"
                  r"(hours?|hrs?|days?|weeks?|wks?|months?)\b", re.IGNORECASE)


def extract_duration_days(text: str) -> float:
    best = 0.0
    for m in _DUR.finditer(text):
        raw = m.group(1).lower().replace(" of", "")
        n = float(raw) if raw.isdigit() else float(_WORD_NUM.get(raw, 0))
        unit = m.group(2).lower()
        if unit.startswith(("hour", "hr")):
            days = n / 24
        elif unit.startswith(("week", "wk")):
            days = n * 7
        elif unit.startswith("month"):
            days = n * 30
        else:
            days = n
        best = max(best, days)
    return float(min(best, 60.0))


_TEMP_CTX = re.compile(r"(?:temp(?:erature)?|fever|febrile)\D{0,15}(\d{2,3}(?:\.\d+)?)\s*(?:°|º|deg(?:rees)?)?\s*([cf])?\b", re.IGNORECASE)
_TEMP_UNIT = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:°|º|deg(?:rees)?)\s*([cf])\b", re.IGNORECASE)
_HR = re.compile(r"(?:\b(\d{2,3})\s*(?:bpm|beats)\b|(?:heart rate|pulse|\bhr\b)\D{0,8}(\d{2,3}))", re.IGNORECASE)
_SPO2 = re.compile(r"(?:spo2|sp02|o2 sat(?:uration)?s?|oxygen(?: saturation| level)?|\bsats?\b)\D{0,12}(\d{2,3})\s*%?", re.IGNORECASE)
_BP = re.compile(r"(?:\bbp\b|blood pressure)\D{0,8}(\d{2,3})\s*/\s*(\d{2,3})|\b(\d{2,3})\s*/\s*(\d{2,3})\s*(?:mm ?hg)\b", re.IGNORECASE)


def _to_c(value: float, unit: Optional[str]) -> Optional[float]:
    if unit and unit.lower() == "f" or value > 45:
        value = (value - 32) * 5 / 9
    return round(value, 1) if 30 <= value <= 43 else None


def extract_vitals(text: str) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {"temp_c": None, "hr": None, "spo2": None, "sbp": None}
    m = _TEMP_CTX.search(text) or _TEMP_UNIT.search(text)
    if m:
        out["temp_c"] = _to_c(float(m.group(1)), m.group(2))
    m = _HR.search(text)
    if m:
        v = float(m.group(1) or m.group(2))
        out["hr"] = v if 20 <= v <= 250 else None
    m = _SPO2.search(text)
    if m:
        v = float(m.group(1))
        out["spo2"] = v if 50 <= v <= 100 else None
    m = _BP.search(text)
    if m:
        v = float(m.group(1) or m.group(3))
        out["sbp"] = v if 50 <= v <= 260 else None
    return out


# --------------------------------------------------------------------------- public API
def extract_symptom_features(text: str) -> dict[str, Optional[float]]:
    """symptoms text -> {sx_*: 0/1, mod_*: 0/1, duration_days, temp_c, hr, spo2, sbp}"""
    text = (text or "")[:4000]
    feats: dict[str, Optional[float]] = {}
    for key, pat in SYMPTOM_PATTERNS.items():
        feats[f"sx_{key}"] = 1.0 if has_unnegated(pat, text) else 0.0
    for key, pat in MODIFIER_PATTERNS.items():
        feats[f"mod_{key}"] = 1.0 if has_unnegated(pat, text) else 0.0
    if feats["mod_severe"]:
        feats["mod_mild"] = 0.0                      # "severe ... mild" -> treat the stronger signal
    feats["duration_days"] = extract_duration_days(text)
    feats.update(extract_vitals(text))
    return feats


def label_for(score: float) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "Urgent"
    if score >= 40:
        return "Moderate"
    return "Routine"


def detected_symptoms(feats: dict) -> list[str]:
    """Human readable list of what the analyser picked up (shown to staff so the AI is explainable)."""
    names = {
        "arrest_collapse": "collapse / unresponsive", "stroke_signs": "stroke signs", "chest_pain": "chest pain",
        "breathing": "breathing difficulty", "bleeding_severe": "severe bleeding", "seizure": "seizure",
        "allergic_severe": "severe allergic reaction", "mental_crisis": "mental-health crisis",
        "pregnancy_issue": "pregnancy complication", "confusion": "confusion", "trauma": "injury / trauma",
        "palpitations": "palpitations", "syncope": "fainting", "abdominal": "abdominal pain", "fever": "fever",
        "neuro_mild": "headache / dizziness", "gi": "nausea / vomiting / diarrhoea", "pain_general": "body / joint pain",
        "skin": "skin problem", "resp_mild": "cough / cold", "routine": "routine / follow-up",
    }
    return [label for key, label in names.items() if feats.get(f"sx_{key}")]


# --------------------------------------------------------------------------- severity weights
# Base urgency (0-100) of each complaint category. NOTE: no recognised complaint may score below UNKNOWN_BASE (30) except
# 'routine', otherwise adding a recognised symptom could LOWER the score and break the monotone safety constraints.
# Base urgency (0-100) of each complaint category. Used by the rule-based "teacher" in services/priority.py
# (which generates the training labels for the XGBoost model) and to rank specialty suggestions.
SYMPTOM_WEIGHT: dict[str, float] = {
    "arrest_collapse": 100, "stroke_signs": 96, "allergic_severe": 90, "bleeding_severe": 85, "seizure": 85, "breathing": 84,
    "chest_pain": 88, "mental_crisis": 80, "pregnancy_issue": 72, "confusion": 70, "trauma": 66, "syncope": 62,
    "palpitations": 55, "abdominal": 52, "fever": 48, "neuro_mild": 42, "gi": 40, "pain_general": 34, "skin": 30,
    "resp_mild": 30, "routine": 12,
}

# --------------------------------------------------------------------------- specialty suggestion
SPECIALTY_HINTS: list[tuple[re.Pattern, str]] = [
    (_rx(r"\bcardi\w+", r"\bheart\b"), "Cardiology"),
    (_rx(r"\bneuro\w*", r"\bbrain\b", r"\bnerve\w*"), "Neurology"),
    (_rx(r"\bpediatric\w*", r"\bpaediatric\w*", r"\bbaby\b", r"\binfant\b", r"\btoddler\b", r"\bmy (?:child|son|daughter|kid)\b"), "Pediatrics"),
    (_rx(r"\bortho\w*", r"\bbones?\b"), "Orthopedics"),
    (_rx(r"\bderm\w*", r"\bskin\b"), "Dermatology"),
    (_rx(r"\boncolog\w*", r"\bcancer\b", r"\bchemo\w*", r"\btumou?r\b"), "Oncology"),
    (_rx(r"\bsurg\w*", r"\bhernia\b", r"\boperation\b"), "Surgery"),
    (_rx(r"\bpsych\w*", r"\banxiety\b", r"\bdepress\w*", r"\bmental health\b", r"\binsomnia\b"), "Psychiatry"),
    (_rx(r"\bx-?ray\b", r"\bmri\b", r"\bct scan\b", r"\bultrasound\b", r"\bradiolog\w*"), "Radiology"),
    (_rx(r"\ban(?:a)?esthe\w*"), "Anesthesiology"),
    (_rx(r"\bambulance\b", r"\bemergency\b"), "Emergency Medicine"),
    (_rx(r"\bgeneral (?:physician|medicine|doctor)\b", r"\bgp\b"), "General Medicine"),
]

_SPECIALTIES_FOR: dict[str, list[str]] = {
    "arrest_collapse": ["Emergency Medicine"], "allergic_severe": ["Emergency Medicine"], "bleeding_severe": ["Emergency Medicine", "Surgery"],
    "seizure": ["Emergency Medicine", "Neurology"], "stroke_signs": ["Neurology", "Emergency Medicine"],
    "breathing": ["General Medicine", "Emergency Medicine"], "chest_pain": ["Cardiology", "Emergency Medicine"],
    "mental_crisis": ["Psychiatry", "Emergency Medicine"], "pregnancy_issue": ["General Medicine", "Emergency Medicine"],
    "confusion": ["Neurology", "General Medicine"], "trauma": ["Orthopedics", "Emergency Medicine", "Surgery"],
    "syncope": ["Cardiology", "Neurology"], "palpitations": ["Cardiology"], "abdominal": ["General Medicine", "Surgery"],
    "fever": ["General Medicine"], "neuro_mild": ["Neurology", "General Medicine"], "gi": ["General Medicine"],
    "pain_general": ["General Medicine", "Orthopedics"], "skin": ["Dermatology"], "resp_mild": ["General Medicine"],
    "routine": ["General Medicine"],
}


def suggest_specialties(feats: dict, age: Optional[int], text: str = "") -> list[str]:
    """Ranked list of hospital specialties (see SPECIALTIES) that best match the complaint."""
    ranked: list[str] = []

    def add(name: str):
        if name not in ranked:
            ranked.append(name)

    for pat, spec in SPECIALTY_HINTS:                                  # the patient named an area explicitly
        if has_unnegated(pat, text or ""):
            add(spec)
    active = sorted((k for k in SYMPTOM_WEIGHT if feats.get(f"sx_{k}")), key=lambda k: -SYMPTOM_WEIGHT[k])
    for k in active:                                                   # most serious complaint first
        for spec in _SPECIALTIES_FOR[k]:
            add(spec)
    if age is not None and age <= 12:
        if "Pediatrics" in ranked:
            ranked.remove("Pediatrics")
        ranked.insert(0, "Pediatrics")                                 # children are seen by paediatrics first
    if not ranked:
        ranked.append("General Medicine")
    return ranked[:4]
