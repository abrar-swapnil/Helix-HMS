"""
services/reassign.py - move patients to another doctor of the SAME specialty when a doctor is unavailable or removed.

  * set a doctor 'unavailable'  -> today's waiting patients move to another doctor of that specialty
  * remove a doctor from roster -> ALL their scheduled appointments (today + future) move; anything that cannot be
    placed is cancelled (the patient sees it) because the doctor no longer exists.
Target doctor: same specialty, not unavailable, preferring the same department (emergency vs general), least loaded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Appointment, Doctor, utcnow
from app.services.queue import next_free_slot, slot_taken, booked_times, waiting_counts
from app.timeutil import today_local


@dataclass
class ReassignResult:
    moved: int = 0
    stranded: int = 0
    cancelled: int = 0
    details: list[dict] = field(default_factory=list)


def _candidates(db: Session, source: Doctor) -> list[Doctor]:
    return (db.query(Doctor).filter(Doctor.specialty == source.specialty, Doctor.is_active.is_(True),
                                    Doctor.status != "unavailable", Doctor.id != source.id).all())


def reassign_doctor_appointments(db: Session, source: Doctor, include_future: bool = False,
                                 cancel_if_stranded: bool = False) -> ReassignResult:
    today = today_local()
    q = db.query(Appointment).filter(Appointment.doctor_id == source.id, Appointment.status == "scheduled")
    q = q.filter(Appointment.date >= today) if include_future else q.filter(Appointment.date == today)
    appts = q.order_by(Appointment.date, Appointment.time, Appointment.id).all()
    result = ReassignResult()
    if not appts:
        return result

    cands = _candidates(db, source)
    load_cache: dict[tuple[int, object], int] = {}

    def load(doc: Doctor, day) -> int:
        key = (doc.id, day)
        if key not in load_cache:
            load_cache[key] = waiting_counts(db, day).get(doc.id, 0)
        return load_cache[key]

    for a in appts:
        pool = cands
        if pool:
            want = "emergency" if a.type == "emergency" else "general"
            preferred = [d for d in pool if d.department == want]
            pool = preferred or pool
        if not pool:
            if cancel_if_stranded:
                a.status, a.cancelled_at, a.cancel_reason = "cancelled", utcnow(), "Doctor removed - no replacement available"
                result.cancelled += 1
            else:
                result.stranded += 1
            continue
        target = min(pool, key=lambda d: (load(d, a.date), d.id))
        a.original_doctor_id = a.original_doctor_id or source.id
        a.doctor_id = target.id
        a.reassigned_at = utcnow()
        if a.type == "general" and slot_taken(booked_times(db, target.id, a.date, exclude_id=a.id), a.time):
            free = next_free_slot(db, target.id, a.date, not_before=a.time)
            if free:
                a.time = free                                  # keep the day, shift to the next free slot
        load_cache[(target.id, a.date)] = load(target, a.date) + 1
        result.moved += 1
        result.details.append({"appointmentId": a.id, "patientId": a.patient_id, "to": target.name, "from": source.name})
    db.flush()
    return result
