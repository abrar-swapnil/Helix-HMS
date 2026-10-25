"""routers/stats.py - dashboard numbers computed from the real database (no hard-coded figures)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Doctor, Room, User
from app.security import doctor_of, require_roles
from app.services.queue import waiting_counts
from app.timeutil import today_local

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _last_7_days():
    today = today_local()
    return [today - timedelta(days=i) for i in range(6, -1, -1)]


@router.get("/admin")
def admin_stats(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    today = today_local()
    docs = db.query(Doctor).filter(Doctor.is_active.is_(True)).all()
    rooms = db.query(Room).all()
    days = _last_7_days()
    rows = (db.query(Appointment.date, func.count(Appointment.id), func.count(func.distinct(Appointment.patient_id)))
            .filter(Appointment.date >= days[0], Appointment.date <= today, Appointment.status != "cancelled")
            .group_by(Appointment.date).all())
    by_day = {d: (a, p) for d, a, p in rows}
    today_rows = db.query(Appointment.type, func.count(Appointment.id)).filter(Appointment.date == today, Appointment.status != "cancelled").group_by(Appointment.type).all()
    today_by_type = dict(today_rows)
    spec_counts: dict[str, int] = {}
    for d in docs:
        spec_counts[d.specialty] = spec_counts.get(d.specialty, 0) + 1
    return {
        "doctors": len(docs), "availableDoctors": sum(1 for d in docs if d.status == "available"),
        "rooms": len(rooms), "availableRooms": sum(1 for r in rooms if r.status == "available"),
        "inpatients": sum(1 for r in rooms if r.status == "occupied"),
        "todayAppointments": sum(today_by_type.values()), "todayEmergency": today_by_type.get("emergency", 0),
        "weekly": [{"day": d.strftime("%a"), "date": d.isoformat(), "appointments": by_day.get(d, (0, 0))[0], "patients": by_day.get(d, (0, 0))[1]} for d in days],
        "specialtyCounts": spec_counts,
    }


@router.get("/doctor")
def doctor_stats(user: User = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    d = doctor_of(db, user)
    today = today_local()
    days = _last_7_days()
    done = db.query(Appointment).filter(Appointment.doctor_id == d.id, Appointment.status == "completed", Appointment.date >= days[0]).all()
    per_day = {x: 0 for x in days}
    for a in done:
        if a.date in per_day:
            per_day[a.date] += 1
    recent = (db.query(Appointment).filter(Appointment.doctor_id == d.id, Appointment.status == "completed")
              .order_by(Appointment.completed_at.desc()).limit(30).all())
    seen, recent_out = set(), []
    for a in recent:
        if a.patient_id in seen:
            continue
        seen.add(a.patient_id)
        recent_out.append({"name": a.patient.name, "age": a.patient.age, "lastVisit": a.date.isoformat()})
        if len(recent_out) == 5:
            break
    return {"seenToday": sum(1 for a in done if a.date == today), "waitingNow": waiting_counts(db).get(d.id, 0),
            "thisWeek": len(done), "weekly": [{"day": x.strftime("%a"), "patients": per_day[x]} for x in days], "recent": recent_out}
