from conftest import new_client, make_patient, _otp_signup


def test_system_starts_empty(admin):
    assert admin.get("/api/doctors").json() == []
    assert admin.get("/api/rooms").json() == []
    s = admin.get("/api/stats/admin").json()
    assert s["doctors"] == 0 and s["rooms"] == 0 and s["todayAppointments"] == 0
    assert all(d["appointments"] == 0 for d in s["weekly"])
    pub = new_client().get("/api/public/stats").json()
    assert pub == {"departments": 0, "doctors": 0, "beds": 0, "patientsServed": 0}


def test_patient_register_requires_otp_then_login_requires_otp(anon):
    u = _otp_signup(anon, {"role": "patient", "username": "Alice_1", "password": "Str0ngPass!", "phone": "+8801711111111"})
    assert u["role"] == "patient" and u["username"] == "alice_1" and u["profileComplete"] is False
    assert anon.get("/api/auth/me").json()["user"]["username"] == "alice_1"
    anon.post("/api/auth/logout")
    assert anon.get("/api/auth/me").status_code == 401
    # login -> OTP challenge
    r = anon.post("/api/auth/login", json={"role": "patient", "username": "ALICE_1", "password": "Str0ngPass!", "phone": "0171-1111111".replace("0171", "+88017")})
    assert r.status_code == 401                                      # phone does not match the account (generic error)
    r = anon.post("/api/auth/login", json={"role": "patient", "username": "alice_1", "password": "Str0ngPass!", "phone": "+880 1711-111111"})
    assert r.status_code == 200 and r.json()["otpRequired"]
    ch = r.json()
    assert anon.post("/api/auth/verify-otp", json={"challengeId": ch["challengeId"], "code": "000000"}).status_code in (400,)
    ok = anon.post("/api/auth/verify-otp", json={"challengeId": ch["challengeId"], "code": ch["devCode"]})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "patient"
    # code is single use
    assert anon.post("/api/auth/verify-otp", json={"challengeId": ch["challengeId"], "code": ch["devCode"]}).status_code == 400


def test_login_errors_are_generic_and_role_is_checked(reception):
    c = new_client()
    for body in ({"role": "receptionist", "username": "rec1", "password": "wrong-password"},
                 {"role": "receptionist", "username": "nobody", "password": "Str0ngPass!"},
                 {"role": "doctor", "username": "rec1", "password": "Str0ngPass!"}):        # right password, wrong role
        r = c.post("/api/auth/login", json=body)
        assert r.status_code == 401 and "Invalid credentials" in r.json()["detail"]
    assert c.post("/api/auth/login", json={"role": "receptionist", "username": "REC1", "password": "Str0ngPass!"}).status_code == 200


def test_bruteforce_lockout(reception):
    c = new_client()
    for _ in range(5):
        assert c.post("/api/auth/login", json={"role": "receptionist", "username": "rec1", "password": "bad-pass-1"}).status_code == 401
    r = c.post("/api/auth/login", json={"role": "receptionist", "username": "rec1", "password": "Str0ngPass!"})
    assert r.status_code == 429                                       # even the right password is blocked while locked


def test_password_and_username_rules(anon):
    base = {"role": "receptionist", "phone": "+8801700000009", "email": "x@h.com"}
    assert anon.post("/api/auth/register", json={**base, "username": "okname", "password": "short"}).status_code == 422
    assert anon.post("/api/auth/register", json={**base, "username": "okname", "password": "password"}).status_code == 422
    assert anon.post("/api/auth/register", json={**base, "username": "a b", "password": "Str0ngPass!"}).status_code == 422
    assert anon.post("/api/auth/register", json={**base, "username": "okname", "password": "Str0ngPass!"}).status_code == 200
    assert new_client().post("/api/auth/register", json={**base, "username": "OKNAME", "password": "Str0ngPass!"}).status_code == 409


def test_password_is_hashed_in_db(reception, db):
    from app.models import User
    u = db.query(User).filter_by(username="rec1").one()
    assert u.password_hash.startswith("$argon2") and "Str0ngPass" not in u.password_hash


def test_csrf_header_required(anon):
    c = new_client()
    del c.headers["X-Requested-With"]
    r = c.post("/api/auth/login", json={"role": "receptionist", "username": "a", "password": "b"})
    assert r.status_code == 403


def test_staff_code_gate(monkeypatch, anon):
    from app.config import settings
    monkeypatch.setattr(settings, "STAFF_SIGNUP_CODE", "s3cret-code")
    assert anon.get("/api/auth/config").json()["staffCodeRequired"] is True
    body = {"role": "receptionist", "username": "rec9", "password": "Str0ngPass!", "phone": "+8801700000009", "email": "x@h.com"}
    assert anon.post("/api/auth/register", json=body).status_code == 403
    assert anon.post("/api/auth/register", json={**body, "staffCode": "wrong"}).status_code == 403
    assert anon.post("/api/auth/register", json={**body, "staffCode": "s3cret-code"}).status_code == 200
    # patients never need the code
    make_patient("pat9", "+8801700000099")


def test_unauthenticated_and_wrong_role_blocked(anon, patient, reception):
    assert anon.get("/api/doctors").status_code == 401
    assert anon.get("/api/appointments").status_code == 401
    assert patient.get("/api/rooms").status_code == 403
    assert patient.get("/api/patients").status_code == 403
    assert patient.post("/api/doctors", json={"name": "X Y", "email": "x@y.com", "specialty": "Cardiology"}).status_code == 403
    assert reception.post("/api/doctors", json={"name": "X Y", "email": "x@y.com", "specialty": "Cardiology"}).status_code == 403
