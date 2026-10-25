"""routers/meta.py - public, non-sensitive info for the landing page (hospital contact details + live aggregate counts)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Appointment, Doctor, Room
from app.schemas import SPECIALTIES
from app.timeutil import now_local, today_local

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/meta")
def meta():
    n = now_local()
    return {"today": today_local().isoformat(), "now": n.isoformat(timespec="seconds"), "timezone": settings.HOSPITAL_TIMEZONE,
            "specialties": SPECIALTIES, "slotMinutes": settings.SLOT_MINUTES, "dayStart": settings.DAY_START, "dayEnd": settings.DAY_END,
            "hospital": {"name": settings.HOSPITAL_NAME, "phone": settings.HOSPITAL_PHONE, "ambulance": settings.HOSPITAL_AMBULANCE,
                         "email": settings.HOSPITAL_EMAIL, "website": settings.HOSPITAL_WEBSITE, "emergency": settings.EMERGENCY_NUMBER}}


@router.get("/public/stats")
def public_stats(db: Session = Depends(get_db)):
    """Real counts for the landing page - aggregates only, no personal data."""
    docs = db.query(func.count(Doctor.id)).filter(Doctor.is_active.is_(True)).scalar() or 0
    depts = db.query(func.count(func.distinct(Doctor.specialty))).filter(Doctor.is_active.is_(True)).scalar() or 0
    beds = db.query(func.count(Room.id)).scalar() or 0
    served = db.query(func.count(func.distinct(Appointment.patient_id))).filter(Appointment.status == "completed").scalar() or 0
    return {"departments": depts, "doctors": docs, "beds": beds, "patientsServed": served}
