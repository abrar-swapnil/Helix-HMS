"""
services/queue.py - queue logic: waiting time, AI scoring of appointments, ordering, slots.

How a queue is ordered
  priority = XGBoost(symptoms + age + medical history + emergency flag + minutes waited so far)
  sort by priority (high first); ties -> who has waited longer; then who booked first.
Waiting time starts at the *later* of "booked" and "scheduled time" (a 9:00 appointment booked yesterday starts
waiting at 9:00); emergencies start waiting on arrival.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Appointment, Doctor, MedicalDocument, Patient, utcnow
from app.services.history import merge_flags
from app.services.priority import build_static_features, model
from app.timeutil import day_slots, hhmm, local_to_utc_naive, now_local, today_local

MAX_MODEL_WAIT = 360.0           # the model was trained on 0-6 h of waiting; beyond that it is flat anyway


# ------------------------------------------------------------------------------------------- waiting time
def wait_start(a: Appointment) -> datetime:
    if a.type == "emergency":
        return a.created_at
    return max(a.created_at, local_to_utc_naive(a.date, a.time))


def wait_minutes(a: Appointment, now: Optional[datetime] = None) -> float:
    """Real-time minutes waited. Only meaningful for scheduled appointments dated today."""
    if a.status != "scheduled" or a.date != today_local():
        return 0.0
    return max(0.0, ((now or utcnow()) - wait_start(a)).total_seconds() / 60.0)


# ------------------------------------------------------------------------------------------- features / scores
def patient_history_flags(db: Session, patient_id: int) -> dict:
    rows = db.query(MedicalDocument.flags).filter(MedicalDocument.patient_id == patient_id).all()
    return merge_flags([r[0] for r in rows])


def rebuild_features(db: Session, appt: Appointment, patient: Optional[Patient] = None) -> None:
    """(Re)compute the model input + condition score for one appointment from the CURRENT patient data."""
    patient = patient or db.get(Patient, appt.patient_id)
    feats = build_static_features(appt.symptoms, patient.age if patient else None,
                                  patient_history_flags(db, appt.patient_id), appt.type == "emergency")
    appt.features = feats
    appt.health_score = model.health(feats)


def rescore_patient(db: Session, patient_id: int) -> int:
    """Called when a patient's documents/profile change: refresh their open appointments."""
    appts = db.query(Appointment).filter(Appointment.patient_id == patient_id, Appointment.status == "scheduled").all()
    patient = db.get(Patient, patient_id)
    for a in appts:
        rebuild_features(db, a, patient)
    return len(appts)


def live_priorities(appts: Iterable[Appointment]) -> dict[int, tuple[float, float]]:
    """{appointment_id: (priority, waited_minutes)} for open appointments - ONE batched model call."""
    now = utcnow()
    open_appts = [a for a in appts if a.status == "scheduled"]
    waits = {a.id: wait_minutes(a, now) for a in open_appts}
    scores = model.priority([(a.features or {}, min(waits[a.id], MAX_MODEL_WAIT)) for a in open_appts])
    return {a.id: (s, waits[a.id]) for a, s in zip(open_appts, scores)}


def sort_key(a: Appointment, prio: dict[int, tuple[float, float]]):
    p, w = prio.get(a.id, (a.health_score, 0.0))
    return (-p, -w, a.id)


def todays_queue(db: Session, doctor_id: int) -> list[Appointment]:
    """Priority-ordered waiting list for one doctor today."""
    appts = db.query(Appointment).filter(Appointment.doctor_id == doctor_id, Appointment.status == "scheduled",
                                         Appointment.date == today_local()).all()
    prio = live_priorities(appts)
    return sorted(appts, key=lambda a: sort_key(a, prio))


def queue_positions(appts: list[Appointment], prio: dict[int, tuple[float, float]]) -> dict[int, int]:
    """position (1-based) of each of today's scheduled appointments inside its doctor's queue"""
    today = today_local()
    groups: dict[int, list[Appointment]] = {}
    for a in appts:
        if a.status == "scheduled" and a.date == today:
            groups.setdefault(a.doctor_id, []).append(a)
    pos: dict[int, int] = {}
    for lst in groups.values():
        for i, a in enumerate(sorted(lst, key=lambda x: sort_key(x, prio)), start=1):
            pos[a.id] = i
    return pos


# ------------------------------------------------------------------------------------------- doctor load
def waiting_counts(db: Session, day: Optional[date] = None) -> dict[int, int]:
    rows = (db.query(Appointment.doctor_id, func.count(Appointment.id))
            .filter(Appointment.status == "scheduled", Appointment.date == (day or today_local()))
            .group_by(Appointment.doctor_id).all())
    return {d: c for d, c in rows}


def seen_today_counts(db: Session) -> dict[int, int]:
    today = today_local()
    rows = (db.query(Appointment.doctor_id, func.count(Appointment.id))
            .filter(Appointment.status == "completed", Appointment.date == today)
            .group_by(Appointment.doctor_id).all())
    return {d: c for d, c in rows}


def est_wait_minutes(waiting: int) -> int:
    return max(5, waiting * settings.AVG_CONSULT_MINUTES)


# ------------------------------------------------------------------------------------------- slots
def booked_times(db: Session, doctor_id: int, day: date, exclude_id: Optional[int] = None) -> list[time]:
    q = db.query(Appointment.time).filter(Appointment.doctor_id == doctor_id, Appointment.date == day,
                                          Appointment.status == "scheduled", Appointment.type == "general")
    if exclude_id:
        q = q.filter(Appointment.id != exclude_id)
    return [r[0] for r in q.all()]


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def slot_taken(taken: list[time], t: time) -> bool:
    return any(abs(_minutes(x) - _minutes(t)) < settings.SLOT_MINUTES for x in taken)


def next_free_slot(db: Session, doctor_id: int, day: date, not_before: Optional[time] = None) -> Optional[time]:
    taken = booked_times(db, doctor_id, day)
    floor = not_before
    if day == today_local():
        n = now_local()
        now_t = time(n.hour, n.minute)
        floor = max(floor, now_t) if floor else now_t
    for s in day_slots():
        if floor and s < floor:
            continue
        if not slot_taken(taken, s):
            return s
    return None


def parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise ValueError("Invalid date (use YYYY-MM-DD).")


def parse_time(s: str) -> time:
    try:
        h, m = s.split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        raise ValueError("Invalid time (use HH:MM).")


def fmt_time(t: time) -> str:
    return hhmm(t)
