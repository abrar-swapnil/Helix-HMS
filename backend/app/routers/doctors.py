"""routers/doctors.py - doctor roster. Admin manages it; everybody signed-in can read it (with role-based redaction)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Doctor, User, utcnow
from app.realtime import bus
from app.routers.auth import doctor_display_name
from app.schemas import DoctorCreateIn, DoctorDepartmentIn, DoctorStatusIn
from app.security import current_user, require_roles
from app.services.presenters import doctors_out
from app.services.queue import est_wait_minutes, parse_date
from app.services.reassign import reassign_doctor_appointments
from app.timeutil import today_local

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


def _active(db: Session, doctor_id: int) -> Doctor:
    d = db.get(Doctor, doctor_id)
    if not d or not d.is_active:
        raise HTTPException(404, "Doctor not found.")
    return d


@router.get("")
def list_doctors(user: User = Depends(current_user), db: Session = Depends(get_db)):
    docs = db.query(Doctor).filter(Doctor.is_active.is_(True)).order_by(Doctor.name).all()
    return doctors_out(db, docs, user)


@router.get("/me")
def my_profile(user: User = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    d = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.is_active.is_(True)).first()
    if not d:
        raise HTTPException(404, "No doctor profile is linked to this account.")
    return doctors_out(db, [d], user)[0]


@router.post("", status_code=201)
def add_doctor(body: DoctorCreateIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.query(Doctor).filter(func.lower(Doctor.email) == email, Doctor.is_active.is_(True)).first():
        raise HTTPException(409, "A doctor with this email is already on the roster.")
    if not body.specialty:
        raise HTTPException(422, "Please choose a specialty.")
    d = Doctor(name=doctor_display_name(body.name), email=email, phone=body.phone, specialty=body.specialty)
    db.add(d)
    db.commit()
    bus.publish(["doctors", "stats"])
    return doctors_out(db, [d], user)[0]


@router.patch("/{doctor_id}/status")
def set_status(doctor_id: int, body: DoctorStatusIn, user: User = Depends(require_roles("admin", "doctor")), db: Session = Depends(get_db)):
    d = _active(db, doctor_id)
    if user.role == "doctor" and d.user_id != user.id:
        raise HTTPException(403, "You can only change your own status.")
    was_unavailable = d.status == "unavailable"
    d.status = body.status
    moved = stranded = 0
    if body.status == "unavailable" and not was_unavailable:
        res = reassign_doctor_appointments(db, d)               # today's waiting patients -> same-specialty doctors
        moved, stranded = res.moved, res.stranded
    db.commit()
    bus.publish(["doctors", "appointments", "stats"])
    return {"doctor": doctors_out(db, [d], user)[0], "moved": moved, "stranded": stranded}


@router.patch("/{doctor_id}/department")
def set_department(doctor_id: int, body: DoctorDepartmentIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    d = _active(db, doctor_id)
    d.department = body.department
    db.commit()
    bus.publish(["doctors"])
    return doctors_out(db, [d], user)[0]


@router.delete("/{doctor_id}")
def remove_doctor(doctor_id: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    d = _active(db, doctor_id)
    d.status = "unavailable"                                    # so they are not chosen as a replacement
    res = reassign_doctor_appointments(db, d, include_future=True, cancel_if_stranded=True)
    d.is_active = False
    if d.user_id:
        acct = db.get(User, d.user_id)
        if acct:
            acct.is_active = False                              # their login stops working immediately
    db.commit()
    bus.publish(["doctors", "appointments", "stats"])
    return {"moved": res.moved, "cancelled": res.cancelled}


@router.get("/{doctor_id}/load")
def doctor_load(doctor_id: int, date: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """How busy is this doctor on a day? (used by the booking dialog)"""
    d = _active(db, doctor_id)
    try:
        day = parse_date(date) if date else today_local()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    n = (db.query(func.count(Appointment.id)).filter(Appointment.doctor_id == d.id, Appointment.status == "scheduled",
                                                     Appointment.date == day).scalar() or 0)
    return {"doctorId": str(d.id), "date": day.isoformat(), "waiting": n, "estWaitMinutes": est_wait_minutes(n)}
