"""
models.py - the database tables.

  users              login accounts (admin / receptionist / doctor / patient)
  doctors            the hospital roster (a doctor may or may not have a login yet)
  patients           patient records (a patient may be a walk-in without a login)
  rooms              hospital rooms / beds
  appointments       general + emergency appointments - THE queue the AI model sorts
  medical_documents  previous medical records (PDF/text/image) used by the AI model
  otp_challenges     one-time codes for admin/patient sign-in and sign-up

All timestamps are stored as naive UTC. Appointment date/time are the hospital's *local* clock time
(see HOSPITAL_TIMEZONE in config.py).
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
                        Time, UniqueConstraint)
from sqlalchemy.dialects.mysql import LONGBLOB, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

BigBlob = LargeBinary().with_variant(LONGBLOB(), "mysql")
BigText = Text().with_variant(MEDIUMTEXT(), "mysql")


def utcnow() -> datetime:
    """Naive UTC 'now' (what we store in every DateTime column)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)       # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)                         # admin|receptionist|doctor|patient
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    specialty: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="available")              # available|busy|unavailable
    department: Mapped[str] = mapped_column(String(20), default="general")            # general|emergency
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)                    # False = removed from roster
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User | None"] = relationship()


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str] = mapped_column(String(40), default="", index=True)
    gender: Mapped[str] = mapped_column(String(10), default="other")                  # male|female|other
    address: Mapped[str] = mapped_column(String(255), default="")
    blood_type: Mapped[str] = mapped_column(String(5), default="")
    profile_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User | None"] = relationship()


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    type: Mapped[str] = mapped_column(String(20), default="general")                  # general|emergency|ot|icu
    status: Mapped[str] = mapped_column(String(20), default="available")              # available|occupied
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)

    patient: Mapped["Patient | None"] = relationship()


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    original_doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True)   # set when reassigned
    date: Mapped[dt.date] = mapped_column(Date, index=True)                              # hospital-local date
    time: Mapped[dt.time] = mapped_column(Time)                                          # hospital-local time
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)  # scheduled|completed|cancelled
    type: Mapped[str] = mapped_column(String(20), default="general")                  # general|emergency
    symptoms: Mapped[str] = mapped_column(Text, default="")
    features: Mapped[dict] = mapped_column(JSON, default=dict)                        # model input (symptoms+age+history)
    health_score: Mapped[float] = mapped_column(Float, default=0)                     # condition-only score 0-100
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)            # arrival / booking time (UTC)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reassigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    booked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    patient: Mapped[Patient] = relationship()
    doctor: Mapped[Doctor] = relationship(foreign_keys=[doctor_id])
    original_doctor: Mapped["Doctor | None"] = relationship(foreign_keys=[original_doctor_id])

    __table_args__ = (Index("ix_appt_doctor_date_status", "doctor_id", "date", "status"),)


class MedicalDocument(Base):
    __tablename__ = "medical_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(BigBlob)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    extracted_text: Mapped[str] = mapped_column(BigText, default="")
    text_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    flags: Mapped[dict] = mapped_column(JSON, default=dict)                           # detected conditions
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(10))                                  # login|register
    role: Mapped[str] = mapped_column(String(20))
    phone: Mapped[str] = mapped_column(String(40))
    code_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)                         # pending sign-up data / user id
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
