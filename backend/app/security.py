"""
security.py - passwords, sessions, role checks, brute-force throttling.

  * Passwords are hashed with Argon2id (never stored or logged in plain text).
  * A session is a signed JWT in an HttpOnly + SameSite=Lax cookie (JavaScript cannot read it;
    cookie is HTTPS-only in production). The user row is re-checked on EVERY request, so disabling an
    account takes effect immediately.
  * Repeated failed logins for the same (ip, username) are temporarily locked out.
"""
from __future__ import annotations

import hmac
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Doctor, Patient, User

ROLES = ("admin", "receptionist", "doctor", "patient")
STAFF_ROLES = ("admin", "receptionist", "doctor")

_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash("not-a-real-password")          # used to keep login timing similar for unknown users

_COMMON = {"password", "password1", "12345678", "123456789", "1234567890", "qwertyui", "qwerty123", "iloveyou", "admin123",
           "11111111", "abcd1234", "letmein1", "welcome1"}


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: Optional[str], password: str) -> bool:
    try:
        return _ph.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password is too long (max 128 characters)."
    if password.lower() in _COMMON or len(set(password)) < 4:
        return "That password is too easy to guess. Please choose another."
    return None


def check_staff_code(code: str) -> bool:
    """Staff sign-up gate. True if no code is configured (open signup) or the supplied code matches."""
    if not settings.staff_code_required:
        return True
    return hmac.compare_digest((code or "").encode(), settings.STAFF_SIGNUP_CODE.encode())


# ----------------------------------------------------------------------------- sessions
def create_session_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "role": user.role, "iat": now, "exp": now + timedelta(hours=settings.SESSION_HOURS)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(settings.COOKIE_NAME, create_session_token(user), max_age=settings.SESSION_HOURS * 3600,
                        httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.COOKIE_NAME, path="/")


def _user_from_request(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        return None
    try:
        data = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user = db.get(User, int(data["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    if not user or not user.is_active or user.role != data.get("role"):
        return None
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    return _user_from_request(request, db)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _user_from_request(request, db)
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to do that.")
        return user
    return dep


def doctor_of(db: Session, user: User) -> Doctor:
    doc = db.query(Doctor).filter(Doctor.user_id == user.id, Doctor.is_active.is_(True)).first()
    if not doc:
        raise HTTPException(404, "No doctor profile is linked to this account.")
    return doc


def patient_of(db: Session, user: User) -> Patient:
    pat = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not pat:
        raise HTTPException(404, "No patient record is linked to this account.")
    return pat


# ----------------------------------------------------------------------------- brute-force throttle
class LoginThrottle:
    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        window = settings.LOGIN_LOCK_MINUTES * 60
        arr = [t for t in self._fails.get(key, []) if now - t < window]
        if arr:
            self._fails[key] = arr
        else:
            self._fails.pop(key, None)
        return arr

    def check(self, key: str) -> None:
        with self._lock:
            if len(self._prune(key, time.time())) >= settings.MAX_LOGIN_FAILURES:
                raise HTTPException(429, f"Too many failed attempts. Try again in {settings.LOGIN_LOCK_MINUTES} minutes.")

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key, time.time())
            self._fails.setdefault(key, []).append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


throttle = LoginThrottle()


class RateLimiter:
    """Tiny in-memory sliding-window limiter (per key, N hits per 60 s) - used for the public chatbot."""
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        now = time.time()
        with self._lock:
            arr = [t for t in self._hits.get(key, []) if now - t < 60]
            if len(arr) >= limit:
                self._hits[key] = arr
                return False
            arr.append(now)
            self._hits[key] = arr
            if len(self._hits) > 5000:                       # keep memory bounded
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 60}
            return True


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
