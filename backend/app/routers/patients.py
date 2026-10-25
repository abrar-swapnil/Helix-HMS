"""
routers/patients.py - patient records and their medical documents.

Who can do what
  receptionist : list / add patients, upload + view + delete any patient's documents
  patient      : read & update their OWN profile, upload / view / delete their OWN documents
  doctor       : VIEW documents of patients they have an appointment with (read-only)
  admin        : no access to patient records (only anonymous statistics)
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Appointment, Doctor, MedicalDocument, Patient, User
from app.realtime import bus
from app.schemas import PatientCreateIn, PatientProfileIn
from app.security import current_user, patient_of, require_roles
from app.services import history
from app.services.presenters import documents_out, patients_out
from app.services.queue import rescore_patient

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("")
def list_patients(q: str = "", user: User = Depends(require_roles("receptionist")), db: Session = Depends(get_db)):
    query = db.query(Patient)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(Patient.name.like(like), Patient.phone.like(like)))
    return patients_out(db, query.order_by(Patient.name).limit(500).all())


@router.post("", status_code=201)
def add_patient(body: PatientCreateIn, user: User = Depends(require_roles("receptionist")), db: Session = Depends(get_db)):
    p = Patient(name=body.name, age=body.age, phone=body.phone, gender=body.gender, address=body.address,
                blood_type=body.blood_type, profile_complete=True)
    db.add(p)
    db.commit()
    bus.publish(["patients", "stats"])
    return patients_out(db, [p])[0]


@router.get("/me")
def my_record(user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    return patients_out(db, [patient_of(db, user)])[0]


@router.patch("/me")
def update_my_record(body: PatientProfileIn, user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    p = patient_of(db, user)
    p.name, p.age, p.gender, p.blood_type, p.address = body.name, body.age, body.gender, body.blood_type, body.address
    p.profile_complete = True
    user.full_name = body.name
    rescore_patient(db, p.id)                                   # age changed -> refresh AI scores of open appointments
    db.commit()
    bus.publish(["patients", "appointments"])
    return patients_out(db, [p])[0]


# ------------------------------------------------------------------------------------------- documents
def _can_access(db: Session, user: User, patient_id: int, write: bool) -> None:
    if user.role == "receptionist":
        return
    if user.role == "patient":
        own = db.query(Patient).filter(Patient.user_id == user.id).first()
        if own and own.id == patient_id:
            return
    elif user.role == "doctor" and not write:
        seen = (db.query(Appointment.id).join(Doctor, Appointment.doctor_id == Doctor.id)
                .filter(Appointment.patient_id == patient_id, Appointment.status != "cancelled", Doctor.user_id == user.id).first())
        if seen:
            return
    raise HTTPException(403, "You do not have access to this patient's records.")


@router.get("/{patient_id}/documents")
def list_documents(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _can_access(db, user, patient_id, write=False)
    docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
    return documents_out(docs)


@router.post("/{patient_id}/documents", status_code=201)
def upload_document(patient_id: int, file: UploadFile = File(...), notes: str = Form(""),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    _can_access(db, user, patient_id, write=True)
    if not db.get(Patient, patient_id):
        raise HTTPException(404, "Patient not found.")
    if db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).count() >= settings.MAX_DOCS_PER_PATIENT:
        raise HTTPException(409, f"Document limit reached ({settings.MAX_DOCS_PER_PATIENT}). Delete an old one first.")
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is too large (max {settings.MAX_UPLOAD_MB} MB).")
    if not data:
        raise HTTPException(422, "The file is empty.")
    name = history.safe_filename(file.filename)
    try:
        ctype = history.sniff_type(name, data)
    except history.UploadError as exc:
        raise HTTPException(415, str(exc))
    notes = (notes or "").strip()[:1000]
    text, extracted = history.extract_text(ctype, data)
    flags = history.detect_conditions(text + "\n" + notes)
    doc = MedicalDocument(patient_id=patient_id, filename=name, content_type=ctype, size=len(data), data=data, notes=notes,
                          extracted_text=text, text_extracted=extracted, flags=flags, uploaded_by_user_id=user.id)
    db.add(doc)
    db.flush()
    rescore_patient(db, patient_id)                             # new history -> new AI scores for waiting appointments
    db.commit()
    bus.publish(["documents", "appointments", "patients"])
    return documents_out([doc])[0]


@router.get("/{patient_id}/documents/{doc_id}/download")
def download_document(patient_id: int, doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _can_access(db, user, patient_id, write=False)
    doc = db.query(MedicalDocument).filter(MedicalDocument.id == doc_id, MedicalDocument.patient_id == patient_id).first()
    if not doc:
        raise HTTPException(404, "Document not found.")
    return Response(content=doc.data, media_type=doc.content_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.filename)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.delete("/{patient_id}/documents/{doc_id}")
def delete_document(patient_id: int, doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _can_access(db, user, patient_id, write=True)
    doc = db.query(MedicalDocument).filter(MedicalDocument.id == doc_id, MedicalDocument.patient_id == patient_id).first()
    if not doc:
        raise HTTPException(404, "Document not found.")
    db.delete(doc)
    db.flush()
    rescore_patient(db, patient_id)
    db.commit()
    bus.publish(["documents", "appointments", "patients"])
    return {"ok": True}
