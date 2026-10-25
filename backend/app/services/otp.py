"""
services/otp.py - one-time codes for admin / patient sign-in and sign-up.

OTP_MODE=demo    the code is returned to the browser so a demo works without an SMS provider (NOT secure - the code is
                 visible to whoever calls the API; only use for demos / local development).
OTP_MODE=twilio  the code is sent by SMS through Twilio (set TWILIO_* in .env). The code is never returned.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OtpChallenge, utcnow

log = logging.getLogger("helix.otp")
RESEND_COOLDOWN_SECONDS = 30
MAX_ATTEMPTS = 5


def digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def same_phone(a: str, b: str) -> bool:
    da, db_ = digits(a), digits(b)
    return bool(da) and bool(db_) and da.lstrip("0") == db_.lstrip("0")


def _hash(challenge_id: str, code: str) -> str:
    return hashlib.sha256(f"{challenge_id}:{code}:{settings.JWT_SECRET}".encode()).hexdigest()


def _deliver(phone: str, code: str) -> Optional[str]:
    """Send the code. Returns the code only in demo mode (so the UI can show it)."""
    if settings.OTP_MODE == "twilio":
        try:
            r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json",
                           data={"To": phone, "From": settings.TWILIO_FROM_NUMBER,
                                 "Body": f"{settings.HOSPITAL_NAME} verification code: {code} (valid {settings.OTP_TTL_SECONDS // 60} min)"},
                           auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN), timeout=10)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("Twilio SMS failed: %s", exc)
            raise HTTPException(502, "Could not send the verification SMS. Please try again.")
        return None
    log.info("[demo OTP] %s -> %s", phone, code)
    return code


def new_challenge(db: Session, purpose: str, role: str, phone: str, payload: dict) -> tuple[OtpChallenge, Optional[str]]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    ch = OtpChallenge(id=uuid.uuid4().hex, purpose=purpose, role=role, phone=phone, payload=payload,
                      code_hash="", expires_at=utcnow() + timedelta(seconds=settings.OTP_TTL_SECONDS))
    ch.code_hash = _hash(ch.id, code)
    shown = _deliver(phone, code)
    db.add(ch)
    db.commit()
    # tidy up old/consumed challenges now and then
    db.query(OtpChallenge).filter(OtpChallenge.expires_at < utcnow() - timedelta(days=1)).delete()
    db.commit()
    return ch, shown


def resend(db: Session, challenge_id: str) -> tuple[OtpChallenge, Optional[str]]:
    ch = db.get(OtpChallenge, challenge_id)
    if not ch or ch.consumed:
        raise HTTPException(400, "This verification has expired. Please start again.")
    if (utcnow() - ch.last_sent_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise HTTPException(429, "Please wait a few seconds before requesting a new code.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    shown = _deliver(ch.phone, code)
    ch.code_hash, ch.attempts = _hash(ch.id, code), 0
    ch.last_sent_at, ch.expires_at = utcnow(), utcnow() + timedelta(seconds=settings.OTP_TTL_SECONDS)
    db.commit()
    return ch, shown


def check(db: Session, challenge_id: str, code: str) -> OtpChallenge:
    ch = db.get(OtpChallenge, challenge_id)
    if not ch or ch.consumed or ch.expires_at < utcnow():
        raise HTTPException(400, "This code has expired. Please request a new one.")
    if ch.attempts >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many wrong codes. Please start again.")
    ch.attempts += 1
    if not hmac.compare_digest(ch.code_hash, _hash(ch.id, (code or "").strip())):
        db.commit()
        raise HTTPException(400, "Incorrect code.")
    ch.consumed = True
    db.commit()
    return ch
