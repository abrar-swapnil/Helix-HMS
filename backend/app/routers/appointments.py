"""
routers/appointments.py - book / list / cancel / upgrade / complete appointments.

The AI part: every booking stores the model input (symptoms + age + medical history); the queue is re-scored with the
patient's REAL waiting time each time it is read (see services/queue.py).
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Doctor, Patient, User, utcnow
from app.realtime import bus
from app.schemas import AppointmentCreateIn, SelfBookIn
from app.security import current_user, doctor_of, patient_of, require_roles
from app.services import otp as otp_util
from app.services.presenters import appointments_out, appt_query
from app.services.queue import (booked_times, next_free_slot, parse_date, parse_time, rebuild_features, slot_taken,
                                todays_queue)
from app.timeutil import now_local, today_local

router = APIRouter(prefix="/api/appointments", tags=["appointments"])
HISTORY_DAYS = 14
MAX_OPEN_PER_PATIENT = 10


def _bookable_doctor(db: Session, doctor_id: int) -> Doctor:
    d = db.get(Doctor, doctor_id)
    if not d or not d.is_active:
        raise HTTPException(404, "Doctor not found.")
    if d.status == "unavailable":
        raise HTTPException(409, f"{d.name} is not available right now. Please choose another doctor.")
    return d


def _find_or_create_patient(db: Session, body: AppointmentCreateIn) -> Patient:
    if body.patient_id:
        p = db.get(Patient, body.patient_id)
        if not p:
            raise HTTPException(404, "Patient not found.")
        return p
    info = body.patient
    p: Optional[Patient] = None
    digits = otp_util.digits(info.phone)
    if digits:
        for cand in db.query(Patient).filter(Patient.phone != "").all():
            if otp_util.digits(cand.phone) == digits and cand.name.strip().lower() == info.name.strip().lower():
                p = cand
                break
    if p is None:
        p = Patient(name=info.name, phone=info.phone, age=info.age, blood_type=info.blood_type, profile_complete=True)
        db.add(p)
        db.flush()
    else:                                                        # fill blanks only, never overwrite what is on record
        p.age = p.age if p.age is not None else info.age
        p.blood_type = p.blood_type or info.blood_type
    return p


def _check_duplicate(db: Session, patient_id: int, doctor_id: int, day) -> None:
    dup = db.query(Appointment.id).filter(Appointment.patient_id == patient_id, Appointment.doctor_id == doctor_id,
                                          Appointment.date == day, Appointment.status == "scheduled").first()
    if dup:
        raise HTTPException(409, "This patient already has an appointment with this doctor on that day.")


# ------------------------------------------------------------------------------------------- read
@router.get("")
def list_appointments(user: User = Depends(require_roles("receptionist", "patient", "doctor")), db: Session = Depends(get_db)):
    q = appt_query(db)
    cutoff = today_local() - timedelta(days=HISTORY_DAYS)
    if user.role == "patient":
        q = q.filter(Appointment.patient_id == patient_of(db, user).id)
    elif user.role == "doctor":
        q = q.filter(Appointment.doctor_id == doctor_of(db, user).id)
    if user.role != "patient":
        q = q.filter((Appointment.status == "scheduled") | (Appointment.date >= cutoff))
    appts = q.order_by(Appointment.date.desc(), Appointment.time.desc()).limit(1500).all()
    return appointments_out(db, appts, user.role)


@router.get("/queue/me")
def my_queue(user: User = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    """The doctor's waiting list for today, ordered by the AI priority model (most urgent first)."""
    d = doctor_of(db, user)
    ids = [a.id for a in todays_queue(db, d.id)]
    if not ids:
        return []
    appts = {a.id: a for a in appt_query(db).filter(Appointment.id.in_(ids)).all()}
    return appointments_out(db, [appts[i] for i in ids], "doctor")


# ------------------------------------------------------------------------------------------- reception books
@router.post("", status_code=201)
def reception_book(body: AppointmentCreateIn, user: User = Depends(require_roles("receptionist")), db: Session = Depends(get_db)):
    doc = _bookable_doctor(db, body.doctor_id)
    want_dept = "emergency" if body.type == "emergency" else "general"
    if doc.department != want_dept:
        raise HTTPException(409, f"{doc.name} works in the {doc.department} department - choose a {want_dept}-department doctor.")
    today = today_local()
    if body.type == "emergency":
        day, slot = today, now_local().time().replace(second=0, microsecond=0)
    else:
        try:
            day = parse_date(body.date) if body.date else today
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if day < today or day > today + timedelta(days=365):
            raise HTTPException(422, "Choose a date from today up to one year ahead.")
        slot = next_free_slot(db, doc.id, day)
        if slot is None:
            raise HTTPException(409, "No free slots left on that date for this doctor.")
    patient = _find_or_create_patient(db, body)
    if body.type == "general":
        _check_duplicate(db, patient.id, doc.id, day)
    appt = Appointment(patient_id=patient.id, doctor_id=doc.id, date=day, time=slot, status="scheduled", type=body.type,
                       symptoms=(body.patient.symptoms or "").strip(), created_at=utcnow(), booked_by_user_id=user.id)
    rebuild_features(db, appt, patient)
    db.add(appt)
    db.commit()
    bus.publish(["appointments", "patients", "doctors", "stats"])
    return appointments_out(db, appt_query(db).filter(Appointment.id == appt.id).all(), "receptionist")[0]


# ------------------------------------------------------------------------------------------- patient books
@router.post("/self", status_code=201)
def patient_book(body: SelfBookIn, user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    patient = patient_of(db, user)
    doc = _bookable_doctor(db, body.doctor_id)
    if doc.department != "general":
        raise HTTPException(409, "This doctor only handles emergency cases. Please choose another doctor or visit the emergency desk.")
    try:
        day, slot = parse_date(body.date), parse_time(body.time)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    now = now_local()
    if day < now.date() or day > now.date() + timedelta(days=365):
        raise HTTPException(422, "Choose a date from today up to one year ahead.")
    if day == now.date() and (slot.hour, slot.minute) < (now.hour, now.minute):
        raise HTTPException(422, "That time has already passed today.")
    open_count = db.query(func.count(Appointment.id)).filter(Appointment.patient_id == patient.id, Appointment.status == "scheduled").scalar() or 0
    if open_count >= MAX_OPEN_PER_PATIENT:
        raise HTTPException(409, f"You already have {MAX_OPEN_PER_PATIENT} upcoming appointments. Cancel one to book another.")
    if slot_taken(booked_times(db, doc.id, day), slot):
        raise HTTPException(409, "That time slot is already booked. Please choose another time.")
    _check_duplicate(db, patient.id, doc.id, day)
    appt = Appointment(patient_id=patient.id, doctor_id=doc.id, date=day, time=slot, status="scheduled", type="general",
                       symptoms=(body.symptoms or "").strip(), created_at=utcnow(), booked_by_user_id=user.id)
    rebuild_features(db, appt, patient)
    db.add(appt)
    db.commit()
    bus.publish(["appointments", "doctors", "stats"])
    return appointments_out(db, appt_query(db).filter(Appointment.id == appt.id).all(), "patient")[0]


# ------------------------------------------------------------------------------------------- state changes
def _get(db: Session, appt_id: int) -> Appointment:
    a = db.get(Appointment, appt_id)
    if not a:
        raise HTTPException(404, "Appointment not found.")
    return a


@router.post("/{appt_id}/cancel")
def cancel(appt_id: int, user: User = Depends(require_roles("receptionist", "patient")), db: Session = Depends(get_db)):
    a = _get(db, appt_id)
    if user.role == "patient" and a.patient_id != patient_of(db, user).id:
        raise HTTPException(403, "This is not your appointment.")
    if a.status != "scheduled":
        raise HTTPException(409, f"This appointment is already {a.status}.")
    a.status, a.cancelled_at = "cancelled", utcnow()
    a.cancel_reason = "Cancelled by patient" if user.role == "patient" else "Cancelled by reception"
    db.commit()
    bus.publish(["appointments", "doctors", "stats"])
    return {"ok": True}


@router.post("/{appt_id}/upgrade")
def upgrade_to_emergency(appt_id: int, user: User = Depends(require_roles("receptionist")), db: Session = Depends(get_db)):
    a = _get(db, appt_id)
    if a.status != "scheduled" or a.type == "emergency":
        raise HTTPException(409, "Only a scheduled general appointment can be upgraded.")
    a.type, a.date, a.created_at = "emergency", today_local(), utcnow()       # emergency clock starts now
    a.time = now_local().time().replace(second=0, microsecond=0)
    rebuild_features(db, a)
    db.commit()
    bus.publish(["appointments", "doctors", "stats"])
    return appointments_out(db, appt_query(db).filter(Appointment.id == a.id).all(), "receptionist")[0]


@router.post("/{appt_id}/complete")
def complete(appt_id: int, user: User = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    a = _get(db, appt_id)
    if a.doctor_id != doctor_of(db, user).id:
        raise HTTPException(403, "This patient is not in your queue.")
    if a.status != "scheduled":
        raise HTTPException(409, f"This appointment is already {a.status}.")
    a.status, a.completed_at = "completed", utcnow()
    db.commit()
    bus.publish(["appointments", "doctors", "patients", "stats"])
    return {"ok": True}
