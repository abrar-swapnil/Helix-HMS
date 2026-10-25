"""
routers/auth.py - register / sign in / OTP / sign out / current user.

Flow summary
  patient & admin : register or login -> OTP code (SMS, or shown on screen in demo mode) -> signed in
  doctor & reception : register or login -> signed in
  staff registration is protected by STAFF_SIGNUP_CODE (see config.py) so strangers cannot become admins.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Doctor, Patient, User, utcnow
from app.realtime import bus
from app.schemas import SPECIALTIES, LoginIn, OtpResendIn, OtpVerifyIn, RegisterIn
from app.security import (check_staff_code, clear_session_cookie, client_ip, current_user, hash_password, password_problem,
                          rate_limiter, set_session_cookie, throttle, verify_password)
from app.services import otp

router = APIRouter(prefix="/api/auth", tags=["auth"])
OTP_ROLES = ("admin", "patient")
USERNAME_RX = re.compile(r"^[a-z0-9._-]{3,30}$")


def doctor_display_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip())
    return name if re.match(r"(?i)^dr\.?\s", name) else f"Dr. {name}"


def user_out(db: Session, user: User) -> dict:
    out = {"id": str(user.id), "role": user.role, "username": user.username, "name": user.full_name,
           "email": user.email or "", "phone": user.phone or "", "profileComplete": True}
    if user.role == "doctor":
        d = db.query(Doctor).filter(Doctor.user_id == user.id).first()
        out["doctorId"] = str(d.id) if d else None
        if d:
            out["name"] = d.name
    elif user.role == "patient":
        p = db.query(Patient).filter(Patient.user_id == user.id).first()
        out["patientId"] = str(p.id) if p else None
        out["profileComplete"] = bool(p and p.profile_complete)
        if p:
            out["name"] = p.name
    return out


def _finish(db: Session, user: User, response: Response, key: str | None = None) -> dict:
    user.last_login_at = utcnow()
    db.commit()
    if key:
        throttle.clear(key)
    set_session_cookie(response, user)
    return {"user": user_out(db, user)}


def _create_account(db: Session, d: dict) -> User:
    """Create the user (+ doctor / patient record) from validated registration data."""
    role = d["role"]
    if db.query(User).filter(User.username == d["username"]).first():
        raise HTTPException(409, "That username is already taken.")
    if role == "doctor":
        email = d["email"].lower()
        doc = db.query(Doctor).filter(func.lower(Doctor.email) == email, Doctor.is_active.is_(True)).first()
        if doc and doc.user_id:
            raise HTTPException(409, "A doctor account already exists for this email.")
        full_name = doc.name if doc else doctor_display_name(d["fullName"])
    else:
        doc, full_name = None, (d.get("fullName") or d["username"]).strip()
    user = User(username=d["username"], password_hash=d["password_hash"], role=role, full_name=full_name,
                email=d.get("email") or None, phone=d.get("phone") or None)
    db.add(user)
    db.flush()
    changed = []
    if role == "doctor":
        if doc:                                                  # admin had already added this doctor to the roster -> link
            doc.user_id = user.id
            doc.phone = doc.phone or d.get("phone", "")
        else:
            db.add(Doctor(user_id=user.id, name=full_name, email=email, phone=d.get("phone", ""), specialty=d["specialty"]))
        changed = ["doctors", "stats"]
    elif role == "patient":
        db.add(Patient(user_id=user.id, name=d["username"], phone=d.get("phone", ""), profile_complete=False))
        changed = ["patients", "stats"]
    db.commit()
    if changed:
        bus.publish(changed)
    return user


@router.get("/config")
def auth_config():
    return {"staffCodeRequired": settings.staff_code_required, "otpMode": settings.OTP_MODE}


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not rate_limiter.allow(f"reg:{client_ip(request)}", 10):
        raise HTTPException(429, "Too many sign-up attempts. Please wait a minute.")
    username = body.username.strip().lower()
    if not USERNAME_RX.match(username):
        raise HTTPException(422, "Username must be 3-30 characters: letters, numbers, dot, dash or underscore.")
    if body.role != "patient" and not check_staff_code(body.staff_code):
        raise HTTPException(403, "Invalid staff access code.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "That username is already taken.")

    role = body.role
    missing = [lbl for lbl, val in (("email", body.email), ("phone", body.phone)) if not val] if role != "patient" else \
              ([] if body.phone else ["phone"])
    if role == "doctor":
        if not body.full_name:
            missing.append("full name")
        if body.specialty not in SPECIALTIES:
            raise HTTPException(422, "Please choose your specialty.")
    if missing:
        raise HTTPException(422, "Please provide: " + ", ".join(missing) + ".")

    data = {"role": role, "username": username, "password_hash": hash_password(body.password), "email": body.email,
            "phone": body.phone, "fullName": body.full_name, "specialty": body.specialty}
    if role in OTP_ROLES:
        if not rate_limiter.allow(f"otp:{otp.digits(body.phone)}", 5):
            raise HTTPException(429, "Too many codes requested for this number. Please wait a minute.")
        ch, shown = otp.new_challenge(db, "register", role, body.phone, data)
        return {"otpRequired": True, "challengeId": ch.id, "devCode": shown, "phone": body.phone}
    user = _create_account(db, data)
    return _finish(db, user, response)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    key = f"{client_ip(request)}|{username}"
    throttle.check(key)
    user = db.query(User).filter(User.username == username).first()
    ok = verify_password(user.password_hash if user else None, body.password)
    ok = ok and user is not None and user.is_active and user.role == body.role
    if ok and body.role in OTP_ROLES and not otp.same_phone(user.phone or "", body.phone):
        ok = False
    if ok and body.role == "doctor" and body.specialty:
        d = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.is_active.is_(True)).first()
        ok = bool(d and d.specialty == body.specialty)
    if not ok:
        throttle.fail(key)
        raise HTTPException(401, "Invalid credentials. Check your details and try again.")
    if body.role == "doctor" and not db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.is_active.is_(True)).first():
        raise HTTPException(403, "Your doctor profile has been deactivated. Contact the administrator.")

    if body.role in OTP_ROLES:
        if not rate_limiter.allow(f"otp:{otp.digits(user.phone or '')}", 5):
            raise HTTPException(429, "Too many codes requested for this number. Please wait a minute.")
        ch, shown = otp.new_challenge(db, "login", body.role, user.phone or "", {"userId": user.id, "key": key})
        return {"otpRequired": True, "challengeId": ch.id, "devCode": shown, "phone": user.phone}
    return _finish(db, user, response, key)


@router.post("/verify-otp")
def verify_otp(body: OtpVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not rate_limiter.allow(f"verify:{client_ip(request)}", 20):
        raise HTTPException(429, "Too many attempts. Please wait a minute.")
    ch = otp.check(db, body.challenge_id, body.code)
    if ch.purpose == "register":
        user = _create_account(db, ch.payload)
        return _finish(db, user, response)
    user = db.get(User, ch.payload["userId"])
    if not user or not user.is_active:
        raise HTTPException(401, "Account not available.")
    return _finish(db, user, response, ch.payload.get("key"))


@router.post("/resend-otp")
def resend_otp(body: OtpResendIn, db: Session = Depends(get_db)):
    ch, shown = otp.resend(db, body.challenge_id)
    return {"challengeId": ch.id, "devCode": shown}


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user": user_out(db, user)}
