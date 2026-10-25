"""
config.py - every setting lives here, read from environment variables / a .env file.

Nothing else in the code base reads os.environ directly, so this is the one file to look at
when you want to know "what can I configure?".  See backend/.env.example for documentation.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv  # python-dotenv is pulled in by uvicorn[standard]

BASE_DIR = Path(__file__).resolve().parent.parent          # .../backend
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


class Settings:
    # ------------------------------------------------------------------ environment
    APP_ENV: str = os.getenv("APP_ENV", "development").lower()          # development | production
    IS_PROD: bool = APP_ENV == "production"

    # ------------------------------------------------------------------ database
    # MySQL example: mysql+pymysql://user:password@localhost:3306/helix_hms
    # If DATABASE_URL is not set (development only) we fall back to a local SQLite file so the
    # app still starts - but the project is designed for MySQL, so set DATABASE_URL.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    # Hosted MySQL (Aiven, TiDB Cloud, Railway ...) usually REQUIRES an encrypted connection:
    #   DB_SSL_CA=/path/to/ca.pem   verify the server with the provider's CA certificate file, or
    #   DB_SSL=true                 encrypt and verify using the operating system's trusted CAs
    DB_SSL_CA: str = os.getenv("DB_SSL_CA", "").strip()
    DB_SSL: bool = _bool("DB_SSL", False)
    DB_SSL_CA_PEM: str = os.getenv("DB_SSL_CA_PEM", "").replace("\\n", "\n").strip()   # the certificate TEXT (for hosts without file mounts)

    # ------------------------------------------------------------------ security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "").strip()
    JWT_ALGORITHM: str = "HS256"
    SESSION_HOURS: int = _int("SESSION_HOURS", 8)
    COOKIE_NAME: str = "helix_session"
    COOKIE_SECURE: bool = _bool("COOKIE_SECURE", IS_PROD)               # HTTPS-only cookie in production
    # Staff (admin / receptionist / doctor) sign-up is protected by a shared code so strangers on the
    # internet cannot register as an administrator. Patients can always self-register.
    STAFF_SIGNUP_CODE: str = os.getenv("STAFF_SIGNUP_CODE", "").strip()
    ALLOW_OPEN_STAFF_SIGNUP: bool = _bool("ALLOW_OPEN_STAFF_SIGNUP", False)
    MAX_LOGIN_FAILURES: int = _int("MAX_LOGIN_FAILURES", 5)
    LOGIN_LOCK_MINUTES: int = _int("LOGIN_LOCK_MINUTES", 15)

    # ------------------------------------------------------------------ OTP
    OTP_MODE: str = os.getenv("OTP_MODE", "demo").lower()               # demo | twilio
    OTP_TTL_SECONDS: int = _int("OTP_TTL_SECONDS", 300)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

    # ------------------------------------------------------------------ hospital
    HOSPITAL_NAME: str = os.getenv("HOSPITAL_NAME", "Helix HMS")
    HOSPITAL_TIMEZONE: str = os.getenv("HOSPITAL_TIMEZONE", "Asia/Dhaka")   # IANA name
    HOSPITAL_PHONE: str = os.getenv("HOSPITAL_PHONE", "+1 (800) 4-HELIX")
    HOSPITAL_AMBULANCE: str = os.getenv("HOSPITAL_AMBULANCE", "+1 (800) HLX-AMBU")
    HOSPITAL_EMAIL: str = os.getenv("HOSPITAL_EMAIL", "support@helixhms.com")
    HOSPITAL_WEBSITE: str = os.getenv("HOSPITAL_WEBSITE", "helixhms.com")
    EMERGENCY_NUMBER: str = os.getenv("EMERGENCY_NUMBER", "911")
    AVG_CONSULT_MINUTES: int = _int("AVG_CONSULT_MINUTES", 8)           # used for "~N min wait" estimates
    SLOT_MINUTES: int = _int("SLOT_MINUTES", 30)
    DAY_START: str = os.getenv("DAY_START", "09:00")
    DAY_END: str = os.getenv("DAY_END", "17:00")

    # ------------------------------------------------------------------ chatbot (Ollama)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "")               # optional bearer token (reverse proxy)
    OLLAMA_TIMEOUT: int = _int("OLLAMA_TIMEOUT", 120)
    CHAT_RATE_PER_MINUTE: int = _int("CHAT_RATE_PER_MINUTE", 12)

    # ------------------------------------------------------------------ uploads
    MAX_UPLOAD_MB: int = _int("MAX_UPLOAD_MB", 5)
    MAX_DOCS_PER_PATIENT: int = _int("MAX_DOCS_PER_PATIENT", 30)

    # ------------------------------------------------------------------ misc
    CORS_ORIGINS: list[str] = _list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    FRONTEND_DIST: Path = Path(os.getenv("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist")))
    MODEL_DIR: Path = BASE_DIR / "app" / "ml"

    def finalize(self) -> "Settings":
        """Validate + fill defaults. Called once at import time."""
        if not self.DATABASE_URL:
            if self.IS_PROD:
                raise RuntimeError("DATABASE_URL must be set when APP_ENV=production")
            self.DATABASE_URL = f"sqlite:///{BASE_DIR / 'helix_dev.sqlite3'}"
            print("[config] DATABASE_URL not set -> using local SQLite file (development only). "
                  "Set DATABASE_URL to your MySQL server for the real setup.", file=sys.stderr)

        if not self.JWT_SECRET:
            if self.IS_PROD:
                raise RuntimeError("JWT_SECRET must be set when APP_ENV=production "
                                   "(generate one: python -c \"import secrets; print(secrets.token_hex(32))\")")
            # dev: random per-process secret (sessions reset whenever the server restarts)
            self.JWT_SECRET = secrets.token_hex(32)
        elif self.IS_PROD and len(self.JWT_SECRET) < 32:
            raise RuntimeError("JWT_SECRET is too short - use at least 32 characters")

        if self.IS_PROD and not self.STAFF_SIGNUP_CODE and not self.ALLOW_OPEN_STAFF_SIGNUP:
            raise RuntimeError(
                "Refusing to start in production without STAFF_SIGNUP_CODE: anyone on the internet could "
                "register as an administrator. Set STAFF_SIGNUP_CODE (recommended) or, if you really want a "
                "fully open demo, ALLOW_OPEN_STAFF_SIGNUP=true.")
        if self.OTP_MODE not in {"demo", "twilio"}:
            raise RuntimeError("OTP_MODE must be 'demo' or 'twilio'")
        if self.OTP_MODE == "twilio" and not (self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN and self.TWILIO_FROM_NUMBER):
            raise RuntimeError("OTP_MODE=twilio needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER")
        if self.DB_SSL_CA_PEM and not self.DB_SSL_CA:
            import tempfile
            fd, path = tempfile.mkstemp(prefix="helix-db-ca-", suffix=".pem")
            with os.fdopen(fd, "w") as fh:
                fh.write(self.DB_SSL_CA_PEM + "\n")
            self.DB_SSL_CA = path
        if self.DATABASE_URL.startswith("mysql") and "charset=" not in self.DATABASE_URL:
            self.DATABASE_URL += ("&" if "?" in self.DATABASE_URL else "?") + "charset=utf8mb4"
        return self

    @property
    def staff_code_required(self) -> bool:
        return bool(self.STAFF_SIGNUP_CODE)

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


settings = Settings().finalize()
