"""routers/ai.py - AI triage preview (shown while staff/patients type symptoms) and AI engine status."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Doctor, Patient, User
from app.schemas import TriagePreviewIn
from app.security import current_user, require_roles
from app.services import chatbot, otp as otp_util
from app.services.history import labels_for
from app.services.priority import build_static_features, model
from app.services.queue import est_wait_minutes, patient_history_flags, waiting_counts
from app.services.triage import detected_symptoms, label_for, suggest_specialties

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/triage-preview")
def triage_preview(body: TriagePreviewIn, user: User = Depends(require_roles("receptionist", "patient", "doctor")),
                   db: Session = Depends(get_db)):
    """Explainable preview: what the AI understood from the text and the score it would give. Nothing is saved."""
    patient = None
    if user.role == "patient":
        patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    elif body.patient_id:
        patient = db.get(Patient, body.patient_id)
    elif body.phone:
        digits = otp_util.digits(body.phone)
        if digits:
            patient = next((p for p in db.query(Patient).filter(Patient.phone != "").all() if otp_util.digits(p.phone) == digits), None)
    age = body.age if body.age is not None else (patient.age if patient else None)
    hist = patient_history_flags(db, patient.id) if patient else {}
    feats = build_static_features(body.symptoms, age, hist, body.type == "emergency")
    score = model.health(feats)

    spec = suggest_specialties(feats, age, body.symptoms)
    avail = {d.specialty for d in db.query(Doctor).filter(Doctor.is_active.is_(True), Doctor.status != "unavailable").all()}
    out = {"healthScore": int(round(score)), "label": label_for(score), "detected": detected_symptoms(feats),
           "historyFlags": labels_for(feats), "suggestedSpecialties": spec,
           "availableSpecialties": [s for s in spec if s in avail],
           "vitals": {k: feats[k] for k in ("temp_c", "hr", "spo2", "sbp") if feats.get(k) is not None},
           "engine": model.info["engine"], "estWaitMinutes": None}
    if body.doctor_id:
        out["estWaitMinutes"] = est_wait_minutes(waiting_counts(db).get(body.doctor_id, 0))
    return out


@router.get("/status")
async def ai_status(user: User = Depends(require_roles("admin"))):
    return {"priorityModel": model.info, "chatbot": await chatbot.ollama_status(force=True)}
