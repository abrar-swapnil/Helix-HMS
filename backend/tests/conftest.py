"""Test fixtures: a fresh empty SQLite database per test, and helpers that sign in as each role."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="helix_test_")
_test_url = os.environ.get("HELIX_TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.sqlite3"
# These tests DROP ALL TABLES before every test. Refuse to run against anything that is not obviously a throw-away database.
if not _test_url.startswith("sqlite") and "test" not in _test_url.rsplit("/", 1)[-1].split("?")[0].lower():
    raise SystemExit("Refusing to run: HELIX_TEST_DATABASE_URL must point to a database whose NAME contains 'test' "
                     "(e.g. .../helix_test) because the tests wipe it. Your real data is safe.")
os.environ["DATABASE_URL"] = _test_url
os.environ["APP_ENV"] = "development"
os.environ["OTP_MODE"] = "demo"
os.environ["STAFF_SIGNUP_CODE"] = ""
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"          # nothing listens here -> chatbot uses the fallback
os.environ["FRONTEND_DIST"] = str(Path(_tmp) / "no-dist")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.security import rate_limiter, throttle
from app.services.priority import model


@pytest.fixture(autouse=True)
def wide_hours(monkeypatch):
    """Tests must not depend on the time of day they run: open the whole day with 1-minute slots."""
    from app.config import settings
    monkeypatch.setattr(settings, "DAY_START", "00:00")
    monkeypatch.setattr(settings, "DAY_END", "23:59")
    monkeypatch.setattr(settings, "SLOT_MINUTES", 1)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    throttle._fails.clear()
    rate_limiter._hits.clear()
    if not model.available:
        model.load()
    yield


def new_client() -> TestClient:
    c = TestClient(app)
    c.headers.update({"X-Requested-With": "helix"})
    return c


@pytest.fixture
def anon():
    return new_client()


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


def _otp_signup(c: TestClient, body: dict) -> dict:
    r = c.post("/api/auth/register", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["otpRequired"] and d["devCode"]
    v = c.post("/api/auth/verify-otp", json={"challengeId": d["challengeId"], "code": d["devCode"]})
    assert v.status_code == 200, v.text
    return v.json()["user"]


@pytest.fixture
def admin():
    c = new_client()
    _otp_signup(c, {"role": "admin", "username": "admin1", "password": "Str0ngPass!", "phone": "+8801700000001", "email": "a@h.com"})
    return c


@pytest.fixture
def reception():
    c = new_client()
    r = c.post("/api/auth/register", json={"role": "receptionist", "username": "rec1", "password": "Str0ngPass!",
                                          "phone": "+8801700000002", "email": "r@h.com"})
    assert r.status_code == 200, r.text
    return c


def make_doctor_login(username="drsmith", specialty="Cardiology", email="smith@h.com", name="John Smith"):
    c = new_client()
    r = c.post("/api/auth/register", json={"role": "doctor", "username": username, "password": "Str0ngPass!", "phone": "+8801700000003",
                                          "email": email, "fullName": name, "specialty": specialty})
    assert r.status_code == 200, r.text
    return c, r.json()["user"]


@pytest.fixture
def doctor():
    c, _ = make_doctor_login()
    return c


def make_patient(username="pat1", phone="+8801700000010", name="Test Patient", age=40):
    c = new_client()
    u = _otp_signup(c, {"role": "patient", "username": username, "password": "Str0ngPass!", "phone": phone})
    r = c.patch("/api/patients/me", json={"name": name, "age": age, "gender": "female", "bloodType": "O+", "address": "1 Road"})
    assert r.status_code == 200, r.text
    return c, u


@pytest.fixture
def patient():
    return make_patient()[0]
