"""schemas.py - request bodies (camelCase JSON, validated by Pydantic)."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

SPECIALTIES = ["Cardiology", "Neurology", "Pediatrics", "Orthopedics", "Dermatology", "Oncology", "General Medicine", "Surgery",
               "Psychiatry", "Radiology", "Anesthesiology", "Emergency Medicine"]
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True, extra="ignore")


def _clean_phone(v: str) -> str:
    v = (v or "").strip()
    if v and not re.fullmatch(r"[0-9+()\-.\s]{5,25}", v):
        raise ValueError("Enter a valid phone number.")
    return v


def _clean_email(v: str) -> str:
    v = (v or "").strip()
    if v and not _EMAIL.match(v):
        raise ValueError("Enter a valid email address.")
    return v


# ------------------------------------------------------------------------------------------- auth
class RegisterIn(CamelModel):
    role: Literal["admin", "receptionist", "doctor", "patient"]
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=1, max_length=128)
    phone: str = ""
    email: str = ""
    full_name: str = Field("", max_length=100)
    specialty: str = ""
    staff_code: str = Field("", max_length=100)

    _p = field_validator("phone")(_clean_phone)
    _e = field_validator("email")(_clean_email)


class LoginIn(CamelModel):
    role: Literal["admin", "receptionist", "doctor", "patient"]
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)
    phone: str = ""
    specialty: str = ""


class OtpVerifyIn(CamelModel):
    challenge_id: str = Field(max_length=40)
    code: str = Field(min_length=6, max_length=6)


class OtpResendIn(CamelModel):
    challenge_id: str = Field(max_length=40)


class PatientProfileIn(CamelModel):
    name: str = Field(min_length=2, max_length=100)
    age: Optional[int] = Field(None, ge=0, le=120)
    gender: Literal["male", "female", "other"] = "other"
    blood_type: str = ""
    address: str = Field("", max_length=250)

    @field_validator("blood_type")
    @classmethod
    def _bt(cls, v: str) -> str:
        if v and v not in BLOOD_TYPES:
            raise ValueError("Invalid blood type.")
        return v


# ------------------------------------------------------------------------------------------- admin / reception
class DoctorCreateIn(CamelModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=200)
    phone: str = ""
    specialty: str = ""

    _p = field_validator("phone")(_clean_phone)
    _e = field_validator("email")(_clean_email)

    @field_validator("specialty")
    @classmethod
    def _spec(cls, v: str) -> str:
        if v and v not in SPECIALTIES:
            raise ValueError("Unknown specialty.")
        return v


class DoctorStatusIn(CamelModel):
    status: Literal["available", "busy", "unavailable"]


class DoctorDepartmentIn(CamelModel):
    department: Literal["general", "emergency"]


class RoomCreateIn(CamelModel):
    number: str = Field(min_length=1, max_length=20)
    type: Literal["general", "emergency", "ot", "icu"] = "general"


class RoomTypeIn(CamelModel):
    type: Literal["general", "emergency"]


class RoomBookIn(CamelModel):
    patient_id: int


class PatientCreateIn(CamelModel):
    name: str = Field(min_length=2, max_length=100)
    age: Optional[int] = Field(None, ge=0, le=120)
    phone: str = ""
    gender: Literal["male", "female", "other"] = "other"
    address: str = Field("", max_length=250)
    blood_type: str = ""

    _p = field_validator("phone")(_clean_phone)

    @field_validator("blood_type")
    @classmethod
    def _bt(cls, v: str) -> str:
        if v and v not in BLOOD_TYPES:
            raise ValueError("Invalid blood type.")
        return v


class WalkInPatient(CamelModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str = ""
    age: Optional[int] = Field(None, ge=0, le=120)
    blood_type: str = ""
    symptoms: str = Field("", max_length=2000)

    _p = field_validator("phone")(_clean_phone)


class AppointmentCreateIn(CamelModel):
    """Receptionist books on behalf of a patient (general or emergency)."""
    type: Literal["general", "emergency"]
    patient: WalkInPatient
    patient_id: Optional[int] = None
    doctor_id: int
    date: Optional[str] = None                      # YYYY-MM-DD, general only


class SelfBookIn(CamelModel):
    """A signed-in patient books a general appointment for themselves."""
    doctor_id: int
    date: str
    time: str
    symptoms: str = Field("", max_length=2000)


class TriagePreviewIn(CamelModel):
    symptoms: str = Field("", max_length=2000)
    age: Optional[int] = Field(None, ge=0, le=120)
    patient_id: Optional[int] = None
    phone: str = ""
    type: Literal["general", "emergency"] = "general"
    doctor_id: Optional[int] = None


class ChatMessage(CamelModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatIn(CamelModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
