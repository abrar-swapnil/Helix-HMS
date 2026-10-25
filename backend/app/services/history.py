"""
services/history.py - read a patient's previous medical documents and detect chronic conditions.

Pipeline:  uploaded file -> extract_text() -> detect_conditions() -> flags like {"h_diabetes": 1.0, ...}
The union of the flags over all of a patient's documents becomes the "medical history" part of the
AI model's input (see services/priority.py).

  * PDF   -> text layer via pypdf (scanned/image-only PDFs have no text layer -> `text_extracted=False`)
  * TXT/MD/CSV/JSON -> decoded as text
  * PNG/JPG -> stored, but no OCR is performed (OCR needs system packages that free hosts lack);
               staff/patient can type the key conditions into the document's "notes" field instead.

>>> TO EXTEND: add a condition to CONDITIONS below (and to HISTORY_KEYS in services/priority.py + retrain). <<<
"""
from __future__ import annotations

import io
import re
from typing import Optional

from app.services.triage import negated_or_other_person


def _words(*alts: str) -> re.Pattern:
    return re.compile(r"(?:%s)" % "|".join(alts), re.IGNORECASE)


def _acronyms(*alts: str) -> re.Pattern:
    return re.compile(r"(?:%s)" % "|".join(alts))                    # case-sensitive on purpose (MI, AF, CAD ...)


# flag -> (human label, [word patterns (ignore-case), acronym patterns (case-sensitive)])
CONDITIONS: dict[str, tuple[str, list[re.Pattern]]] = {
    "h_cardiac": ("Heart disease", [
        _words(r"coronary (?:artery )?disease", r"myocardial infarction", r"heart attack", r"angina", r"\bstents?\b", r"bypass surgery",
               r"heart failure", r"cardiomyopathy", r"atrial fibrillation", r"arrhythmia", r"pacemaker", r"valve (?:disease|replacement)",
               r"isch(?:a)?emic heart", r"cardiac (?:disease|history)"),
        _acronyms(r"\bCAD\b", r"\bMI\b", r"\bCABG\b", r"\bCHF\b", r"\bAF\b", r"\bIHD\b")]),
    "h_hypertension": ("Hypertension", [
        _words(r"hypertensi\w+", r"high blood pressure", r"amlodipine", r"losartan", r"lisinopril", r"enalapril"), _acronyms(r"\bHTN\b")]),
    "h_diabetes": ("Diabetes", [
        _words(r"diabet\w+", r"\bmetformin\b", r"\binsulin\b", r"gliclazide", r"glimepiride", r"glibenclamide", r"hba1c"),
        _acronyms(r"\bT2DM\b", r"\bT1DM\b", r"\bDM\b")]),
    "h_respiratory": ("Asthma / COPD", [
        _words(r"asthma\w*", r"chronic obstructive", r"emphysema", r"bronchiectasis", r"pulmonary fibrosis", r"chronic bronchitis",
               r"salbutamol", r"albuterol", r"ventolin"), _acronyms(r"\bCOPD\b")]),
    "h_stroke": ("Stroke / TIA", [
        _words(r"\bstroke\b", r"cerebrovascular accident", r"transient isch(?:a)?emic", r"hemipar\w+", r"hemipleg\w+"), _acronyms(r"\bCVA\b", r"\bTIA\b")]),
    "h_cancer": ("Cancer", [
        _words(r"\bcancer\b", r"carcinoma", r"malignan\w+", r"metasta\w+", r"chemotherapy", r"radiotherapy", r"lymphoma", r"leuk(?:a)?emia", r"melanoma")]),
    "h_kidney": ("Kidney disease", [
        _words(r"chronic kidney disease", r"(?:kidney|renal) failure", r"dialysis", r"nephropathy", r"kidney transplant"), _acronyms(r"\bCKD\b", r"\bESRD\b")]),
    "h_liver": ("Liver disease", [
        _words(r"cirrhosis", r"hepatitis [bc]", r"liver failure", r"chronic liver", r"hepatic (?:failure|impairment)")]),
    "h_immuno": ("Immunocompromised", [
        _words(r"immunocompromised", r"immunosuppress\w+", r"transplant", r"prednisolone", r"prednisone", r"methotrexate", r"azathioprine",
               r"tacrolimus", r"cyclosporin\w*"), _acronyms(r"\bHIV\b", r"\bAIDS\b")]),
    "h_anticoag": ("Blood thinners", [
        _words(r"warfarin", r"apixaban", r"rivaroxaban", r"dabigatran", r"clopidogrel", r"enoxaparin", r"heparin", r"ticagrelor",
               r"anticoagulant\w*", r"blood thinners?")]),
    "h_epilepsy": ("Epilepsy", [
        _words(r"epilep\w+", r"anticonvulsant\w*", r"levetiracetam", r"carbamazepine", r"phenytoin", r"valpro\w+")]),
    "h_pregnant": ("Pregnancy", [
        _words(r"\bpregnan\w+", r"\bgestation\w*", r"\bantenatal\b", r"\bweeks pregnant\b")]),
    "h_recent_surgery": ("Recent surgery", [
        _words(r"post-?operative", r"post-?op\b", r"surgery on", r"underwent (?:a |an )?\w*\s?(?:surgery|operation)", r"discharge summary")]),
}
HISTORY_KEYS = list(CONDITIONS)
HISTORY_LABELS = {k: v[0] for k, v in CONDITIONS.items()}


def detect_conditions(text: str) -> dict[str, float]:
    """{'h_diabetes': 1.0, ...} for each condition mentioned (and not negated / not about a relative)."""
    text = (text or "")[:300_000]
    found: dict[str, float] = {}
    for key, (_label, patterns) in CONDITIONS.items():
        for pat in patterns:
            if any(not negated_or_other_person(text, m.start()) for m in pat.finditer(text)):
                found[key] = 1.0
                break
    return found


def labels_for(flags: dict) -> list[str]:
    return [HISTORY_LABELS[k] for k in HISTORY_KEYS if flags.get(k)]


def merge_flags(flag_dicts: list[dict]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for d in flag_dicts:
        for k, v in (d or {}).items():
            if v and k in HISTORY_LABELS:
                merged[k] = 1.0
    return merged


# --------------------------------------------------------------------------- file handling
ALLOWED_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "txt": "text/plain", "md": "text/plain", "csv": "text/plain", "json": "text/plain"}


class UploadError(ValueError):
    pass


def sniff_type(filename: str, data: bytes) -> str:
    """Validate by extension AND magic bytes; returns the content type we will serve the file as."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_TYPES:
        raise UploadError("Unsupported file type. Allowed: PDF, TXT, PNG, JPG.")
    head = data[:8]
    if ext == "pdf" and not data.startswith(b"%PDF-"):
        raise UploadError("This file is not a valid PDF.")
    if ext == "png" and not head.startswith(b"\x89PNG"):
        raise UploadError("This file is not a valid PNG image.")
    if ext in ("jpg", "jpeg") and not data.startswith(b"\xff\xd8\xff"):
        raise UploadError("This file is not a valid JPEG image.")
    if ext in ("txt", "md", "csv", "json") and b"\x00" in data[:4096]:
        raise UploadError("This file is not a text file.")
    return ALLOWED_TYPES[ext]


def extract_text(content_type: str, data: bytes) -> tuple[str, bool]:
    """-> (text, text_extracted). Never raises: a failure just means 'no text'."""
    try:
        if content_type == "text/plain":
            return data.decode("utf-8", errors="ignore")[:300_000], True
        if content_type == "application/pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return "", False
            chunks = []
            for page in reader.pages[:40]:
                chunks.append(page.extract_text() or "")
            text = "\n".join(chunks).strip()
            return text[:300_000], bool(text)
    except Exception:                                                         # corrupt / exotic PDF
        return "", False
    return "", False


def safe_filename(name: Optional[str]) -> str:
    name = (name or "document").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "document"
    return name[:180]
