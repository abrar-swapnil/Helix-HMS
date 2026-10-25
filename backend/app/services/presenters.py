"""
services/presenters.py - turn database rows into the JSON the frontend expects (camelCase, string ids).

Role-based redaction lives here: phone / email are only included for the people who need them.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import Appointment, Doctor, MedicalDocument, Patient, Room, User
from app.services.history import labels_for
from app.services.queue import (est_wait_minutes, live_priorities, queue_positions, seen_today_counts, waiting_counts)
from app.services.triage import detected_symptoms
from app.timeutil import hhmm, today_local, utc_naive_to_local


def code(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def appt_query(db: Session):
    return db.query(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.doctor),
                                         joinedload(Appointment.original_doctor))


# ------------------------------------------------------------------------------------------- doctors
def doctors_out(db: Session, doctors: list[Doctor], viewer: Optional[User]) -> list[dict]:
    waiting, seen = waiting_counts(db), seen_today_counts(db)
    out = []
    for d in doctors:
        w = waiting.get(d.id, 0)
        item = {"id": str(d.id), "code": code("D", d.id), "name": d.name, "specialty": d.specialty, "status": d.status,
                "department": d.department, "waitingCount": w, "patientsToday": seen.get(d.id, 0),
                "estWaitMinutes": est_wait_minutes(w), "hasAccount": d.user_id is not None}
        if viewer and (viewer.role in ("admin", "receptionist") or (viewer.role == "doctor" and d.user_id == viewer.id)):
            item["email"], item["phone"] = d.email, d.phone
        out.append(item)
    return out


# ------------------------------------------------------------------------------------------- patients
def patients_out(db: Session, patients: list[Patient]) -> list[dict]:
    ids = [p.id for p in patients]
    doc_counts: dict[int, int] = {}
    last_doc: dict[int, str] = {}
    if ids:
        doc_counts = dict(db.query(MedicalDocument.patient_id, func.count(MedicalDocument.id))
                          .filter(MedicalDocument.patient_id.in_(ids)).group_by(MedicalDocument.patient_id).all())
        done = (db.query(Appointment).options(joinedload(Appointment.doctor))
                .filter(Appointment.patient_id.in_(ids), Appointment.status == "completed")
                .order_by(Appointment.completed_at.asc()).all())
        for a in done:                                            # ascending -> last write wins = most recent
            last_doc[a.patient_id] = a.doctor.name
    usernames = {p.user_id: p.user.username for p in patients if p.user_id and p.user}
    return [{"id": str(p.id), "code": code("P", p.id), "name": p.name, "age": p.age, "phone": p.phone, "gender": p.gender,
             "address": p.address, "bloodType": p.blood_type, "username": usernames.get(p.user_id, ""),
             "previousDoctor": last_doc.get(p.id), "documentCount": doc_counts.get(p.id, 0),
             "profileComplete": p.profile_complete, "hasAccount": p.user_id is not None} for p in patients]


# ------------------------------------------------------------------------------------------- rooms
def rooms_out(rooms: list[Room]) -> list[dict]:
    return [{"id": str(r.id), "code": code("R", r.id), "number": r.number, "type": r.type, "status": r.status,
             "patientId": str(r.patient_id) if r.patient_id else None, "patientName": r.patient.name if r.patient else None}
            for r in rooms]


# ------------------------------------------------------------------------------------------- appointments
def appointments_out(db: Session, appts: list[Appointment], viewer_role: str) -> list[dict]:
    prio = live_priorities(appts)
    pos = queue_positions(appts, prio)
    show_phone = viewer_role in ("receptionist", "patient")
    out = []
    for a in appts:
        p, w = prio.get(a.id, (a.health_score, 0.0))
        feats = a.features or {}
        out.append({
            "id": str(a.id), "code": code("A", a.id), "patientId": str(a.patient_id), "patientName": a.patient.name,
            "patientPhone": a.patient.phone if show_phone else "", "patientAge": a.patient.age,
            "patientBloodType": a.patient.blood_type, "symptoms": a.symptoms,
            "doctorId": str(a.doctor_id), "doctorName": a.doctor.name, "doctorSpecialty": a.doctor.specialty,
            "doctorUnavailable": a.status == "scheduled" and a.doctor.status == "unavailable",
            "date": a.date.isoformat(), "time": hhmm(a.time), "status": a.status, "type": a.type,
            "healthScore": int(round(a.health_score)), "priorityScore": round(p, 1),
            "waitingMinutes": int(w), "queuePosition": pos.get(a.id),
            "arrivedAt": hhmm(utc_naive_to_local(a.created_at).time()),
            "reassignedFrom": a.original_doctor.name if a.original_doctor and a.original_doctor_id != a.doctor_id else None,
            "historyFlags": labels_for(feats), "detected": detected_symptoms(feats), "cancelReason": a.cancel_reason,
        })
    return out


def documents_out(docs: list[MedicalDocument]) -> list[dict]:
    return [{"id": str(d.id), "filename": d.filename, "contentType": d.content_type, "size": d.size, "notes": d.notes,
             "textExtracted": d.text_extracted, "conditions": labels_for(d.flags or {}),
             "uploadedAt": d.created_at.isoformat() + "Z"} for d in docs]
