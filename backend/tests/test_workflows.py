import io
from datetime import timedelta

from conftest import make_doctor_login, make_patient, new_client
from app.models import Appointment
from app.timeutil import today_local, utcnow, now_local


def add_doc(admin, name="Jane Roe", email="jane@h.com", specialty="Cardiology"):
    r = admin.post("/api/doctors", json={"name": name, "email": email, "phone": "+8801800000001", "specialty": specialty})
    assert r.status_code == 201, r.text
    return r.json()


def book(reception, doctor_id, symptoms, name="Walk In", phone="+8801900000001", age=40, type="general"):
    r = reception.post("/api/appointments", json={"type": type, "doctorId": int(doctor_id), "patient": {
        "name": name, "phone": phone, "age": age, "symptoms": symptoms}})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------------- one source of truth: add / edit / remove everywhere
def test_doctor_added_by_admin_is_visible_to_everyone_and_chatbot(admin, reception, patient):
    d = add_doc(admin)
    assert d["name"] == "Dr. Jane Roe" and d["status"] == "available"
    for c in (admin, reception, patient):
        assert [x["name"] for x in c.get("/api/doctors").json()] == ["Dr. Jane Roe"]
    # redaction: patients never see a doctor's contact details; staff do
    assert "email" not in patient.get("/api/doctors").json()[0]
    assert reception.get("/api/doctors").json()[0]["phone"] == "+8801800000001"
    # public chatbot (not signed in) answers from the live roster
    anon = new_client()
    text = _chat(anon, "Is there a cardiologist?")
    assert "Dr. Jane Roe" in text
    # remove -> gone from all views and from the chatbot
    assert admin.delete(f"/api/doctors/{d['id']}").status_code == 200
    for c in (admin, reception, patient):
        assert c.get("/api/doctors").json() == []
    assert "Dr. Jane Roe" not in _chat(anon, "Is there a cardiologist?")


def _chat(client, msg):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": msg}]})
    assert r.status_code == 200, r.text
    import json
    events = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert events[0]["type"] == "meta" and events[0]["mode"] == "basic"        # no Ollama in tests
    assert events[-1]["type"] == "done"
    return "".join(e.get("text", "") for e in events)


def test_duplicate_doctor_email_rejected_and_doctor_can_claim_profile(admin):
    d = add_doc(admin, email="claim@h.com")
    assert admin.post("/api/doctors", json={"name": "Other", "email": "CLAIM@h.com", "specialty": "ENT"}).status_code in (409, 422)
    doc_client, user = make_doctor_login("claimer", "Cardiology", "claim@h.com", "Whoever")
    assert user["doctorId"] == d["id"] and user["name"] == "Dr. Jane Roe"        # linked to the admin-created roster entry
    assert len(admin.get("/api/doctors").json()) == 1
    assert doc_client.get("/api/doctors/me").json()["id"] == d["id"]


def test_doctor_self_registration_appears_for_everyone(admin, patient):
    make_doctor_login("drself", "Neurology", "self@h.com", "Sam Self")
    names = [d["name"] for d in patient.get("/api/doctors").json()]
    assert names == ["Dr. Sam Self"]
    assert admin.get("/api/stats/admin").json()["doctors"] == 1


# ------------------------------------------------------------------------- the AI queue
def test_queue_is_sorted_by_ai_priority_not_arrival_order(admin, reception):
    d = add_doc(admin)
    book(reception, d["id"], "Follow-up checkup", "Routine Ron", "+8801900000001", 30)
    book(reception, d["id"], "mild cough", "Cough Cathy", "+8801900000002", 30)
    book(reception, d["id"], "severe chest pain radiating to left arm and difficulty breathing", "Critical Carl", "+8801900000003", 62)
    doc_client, _ = make_doctor_login("drq", "Cardiology", "jane@h.com", "x")            # claims Jane's roster entry
    q = doc_client.get("/api/appointments/queue/me").json()
    assert [a["patientName"] for a in q] == ["Critical Carl", "Cough Cathy", "Routine Ron"]
    assert q[0]["queuePosition"] == 1 and q[0]["healthScore"] >= 80 and "chest pain" in q[0]["detected"]
    assert q[0]["priorityScore"] >= q[1]["priorityScore"] >= q[2]["priorityScore"]
    assert "patientPhone" in q[0] and q[0]["patientPhone"] == ""                        # doctors don't get phone numbers


def test_longer_waiting_raises_priority_but_never_beats_a_critical_patient(admin, reception, db):
    d = add_doc(admin)
    admin.patch(f"/api/doctors/{d['id']}/department", json={"department": "emergency"})
    a_mild = book(reception, d["id"], "mild cough", "Old Waiter", "+8801900000001", 30, type="emergency")
    a_urgent = book(reception, d["id"], "high fever 39.5C and severe headache", "Fresh Urgent", "+8801900000002", 30, type="emergency")
    p0 = {a["id"]: a["priorityScore"] for a in reception.get("/api/appointments").json()}
    row = db.get(Appointment, int(a_mild["id"]))               # pretend this patient has been waiting for 3 hours
    row.created_at = utcnow() - timedelta(hours=3)
    db.commit()
    p1 = {a["id"]: a for a in reception.get("/api/appointments").json()}
    assert 175 <= p1[a_mild["id"]]["waitingMinutes"] <= 185
    assert p1[a_mild["id"]]["priorityScore"] > p0[a_mild["id"]] + 5                      # waiting raised it
    assert p1[a_urgent["id"]]["priorityScore"] > p1[a_mild["id"]]["priorityScore"]       # ...but not above a clearly sicker patient


def test_emergency_requires_emergency_department_doctor(admin, reception):
    d = add_doc(admin)
    r = reception.post("/api/appointments", json={"type": "emergency", "doctorId": int(d["id"]), "patient": {"name": "A B", "symptoms": "chest pain"}})
    assert r.status_code == 409 and "department" in r.json()["detail"]
    assert admin.patch(f"/api/doctors/{d['id']}/department", json={"department": "emergency"}).status_code == 200
    e = reception.post("/api/appointments", json={"type": "emergency", "doctorId": int(d["id"]), "patient": {"name": "A B", "symptoms": "chest pain"}})
    assert e.status_code == 201 and e.json()["type"] == "emergency"


def test_patient_self_booking_and_slot_conflicts(admin, patient, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SLOT_MINUTES", 30)
    d = add_doc(admin)
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    body = {"doctorId": int(d["id"]), "date": tomorrow, "time": "10:00", "symptoms": "sore throat for 3 days"}
    r = patient.post("/api/appointments/self", json=body)
    assert r.status_code == 201 and r.json()["status"] == "scheduled"
    other, _ = make_patient("pat2", "+8801700000020", "Other P", 33)
    assert other.post("/api/appointments/self", json={**body, "time": "10:15"}).status_code == 409      # inside the 30 min slot
    assert other.post("/api/appointments/self", json={**body, "time": "11:00"}).status_code == 201
    assert patient.post("/api/appointments/self", json={**body, "time": "14:00"}).status_code == 409    # same doctor same day
    past = (today_local() - timedelta(days=1)).isoformat()
    assert patient.post("/api/appointments/self", json={**body, "date": past}).status_code == 422
    # each patient only sees their own appointments
    assert len(patient.get("/api/appointments").json()) == 1 and len(other.get("/api/appointments").json()) == 1


def test_cancel_upgrade_complete_permissions(admin, reception, patient):
    d = add_doc(admin)
    doc_client, _ = make_doctor_login("drx", "Cardiology", "jane@h.com", "x")
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    a = patient.post("/api/appointments/self", json={"doctorId": int(d["id"]), "date": tomorrow, "time": "09:00", "symptoms": "headache"}).json()
    stranger, _ = make_patient("pat3", "+8801700000030", "Stranger", 50)
    assert stranger.post(f"/api/appointments/{a['id']}/cancel").status_code == 403
    assert patient.post(f"/api/appointments/{a['id']}/complete").status_code == 403
    assert reception.post(f"/api/appointments/{a['id']}/upgrade").json()["type"] == "emergency"
    assert reception.post(f"/api/appointments/{a['id']}/upgrade").status_code == 409
    # doctor completes it -> shows as completed for the patient and in the doctor's stats
    assert doc_client.post(f"/api/appointments/{a['id']}/complete").status_code == 200
    assert patient.get("/api/appointments").json()[0]["status"] == "completed"
    assert doc_client.get("/api/stats/doctor").json()["seenToday"] == 1
    assert patient.post(f"/api/appointments/{a['id']}/cancel").status_code == 409
    assert patient.get("/api/patients/me").json()["previousDoctor"] == "Dr. Jane Roe"


# ------------------------------------------------------------------------- doctor absent -> patients move to same specialty
def test_unavailable_doctor_patients_move_to_same_specialty_only(admin, reception, patient):
    cardio_a = add_doc(admin, "Ann A", "a@h.com", "Cardiology")
    cardio_b = add_doc(admin, "Bob B", "b@h.com", "Cardiology")
    neuro = add_doc(admin, "Nia N", "n@h.com", "Neurology")
    book(reception, cardio_a["id"], "chest pain", "P One", "+8801900000001")
    book(reception, cardio_a["id"], "palpitations", "P Two", "+8801900000002")
    book(reception, neuro["id"], "headache", "P Three", "+8801900000003")
    r = admin.patch(f"/api/doctors/{cardio_a['id']}/status", json={"status": "unavailable"})
    assert r.status_code == 200 and r.json()["moved"] == 2
    by_patient = {a["patientName"]: a for a in reception.get("/api/appointments").json()}
    assert by_patient["P One"]["doctorName"] == "Dr. Bob B" and by_patient["P One"]["reassignedFrom"] == "Dr. Ann A"
    assert by_patient["P Two"]["doctorName"] == "Dr. Bob B"
    assert by_patient["P Three"]["doctorName"] == "Dr. Nia N" and by_patient["P Three"]["reassignedFrom"] is None   # untouched
    docs = {d["name"]: d for d in admin.get("/api/doctors").json()}
    assert docs["Dr. Bob B"]["waitingCount"] == 2 and docs["Dr. Ann A"]["waitingCount"] == 0
    # nobody can book the absent doctor
    assert reception.post("/api/appointments", json={"type": "general", "doctorId": int(cardio_a["id"]), "patient": {"name": "Zed Z"}}).status_code == 409


def test_no_replacement_available_flags_patients_instead_of_losing_them(admin, reception):
    only = add_doc(admin, "Solo S", "s@h.com", "Oncology")
    book(reception, only["id"], "follow-up", "Waiting W", "+8801900000001")
    r = admin.patch(f"/api/doctors/{only['id']}/status", json={"status": "unavailable"}).json()
    assert r["moved"] == 0 and r["stranded"] == 1
    a = reception.get("/api/appointments").json()[0]
    assert a["status"] == "scheduled" and a["doctorUnavailable"] is True


def test_removing_a_doctor_reassigns_or_cancels_and_disables_login(admin, reception, patient, db):
    a = add_doc(admin, "Ann A", "a@h.com", "Cardiology")
    b = add_doc(admin, "Bob B", "b@h.com", "Cardiology")
    solo = add_doc(admin, "Solo S", "s@h.com", "Oncology")
    doc_client, _ = make_doctor_login("drsolo", "Oncology", "s@h.com", "x")
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    book(reception, a["id"], "chest pain", "Move Me", "+8801900000001")
    patient.post("/api/appointments/self", json={"doctorId": int(solo["id"]), "date": tomorrow, "time": "10:00", "symptoms": "follow up"})
    assert admin.delete(f"/api/doctors/{a['id']}").json() == {"moved": 1, "cancelled": 0}
    assert admin.delete(f"/api/doctors/{solo['id']}").json() == {"moved": 0, "cancelled": 1}   # no oncologist left
    mine = patient.get("/api/appointments").json()[0]
    assert mine["status"] == "cancelled" and "removed" in mine["cancelReason"]
    assert doc_client.get("/api/appointments").status_code == 401                              # removed doctor's session is dead
    assert new_client().post("/api/auth/login", json={"role": "doctor", "username": "drsolo", "password": "Str0ngPass!"}).status_code == 401
    assert [d["name"] for d in admin.get("/api/doctors").json()] == ["Dr. Bob B"]


# ------------------------------------------------------------------------- medical documents -> AI
def _upload(client, patient_id, text, name="history.txt", notes=""):
    return client.post(f"/api/patients/{patient_id}/documents", files={"file": (name, io.BytesIO(text.encode()), "text/plain")}, data={"notes": notes})


def test_documents_raise_priority_and_respect_privacy(admin, reception, db):
    d = add_doc(admin)
    doc_client, _ = make_doctor_login("drdoc", "Cardiology", "jane@h.com", "x")
    other_doc, _ = make_doctor_login("drother", "Cardiology", "o@h.com", "Other Doc")
    pat, u = make_patient("hist1", "+8801700000040", "History Hal", 62)
    pid = int(u["id"]) if False else pat.get("/api/patients/me").json()["id"]
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    base = pat.post("/api/appointments/self", json={"doctorId": int(d["id"]), "date": tomorrow, "time": "10:00", "symptoms": "chest tightness and shortness of breath"})
    assert base.status_code == 201
    before = base.json()["healthScore"]
    up = _upload(pat, pid, "Type 2 diabetes on metformin. Hypertension. Coronary artery disease, stent 2019. No history of stroke.")
    assert up.status_code == 201
    assert set(up.json()["conditions"]) == {"Heart disease", "Hypertension", "Diabetes"} and up.json()["textExtracted"] is True
    after = pat.get("/api/appointments").json()[0]
    assert after["healthScore"] >= before and set(after["historyFlags"]) == {"Heart disease", "Hypertension", "Diabetes"}
    # access control
    assert doc_client.get(f"/api/patients/{pid}/documents").status_code == 200              # treating doctor can read
    assert other_doc.get(f"/api/patients/{pid}/documents").status_code == 403               # unrelated doctor cannot
    assert admin.get(f"/api/patients/{pid}/documents").status_code == 403                    # admin has no clinical access
    stranger, _ = make_patient("hist2", "+8801700000041", "Stranger", 30)
    assert stranger.get(f"/api/patients/{pid}/documents").status_code == 403
    assert doc_client.post(f"/api/patients/{pid}/documents", files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 403
    # download is forced as an attachment, never rendered inline
    did = up.json()["id"]
    dl = doc_client.get(f"/api/patients/{pid}/documents/{did}/download")
    assert dl.status_code == 200 and "attachment" in dl.headers["content-disposition"] and dl.headers["x-content-type-options"] == "nosniff"
    # deleting the document removes the history signal again
    assert pat.delete(f"/api/patients/{pid}/documents/{did}").status_code == 200
    assert pat.get("/api/appointments").json()[0]["historyFlags"] == []


def test_upload_validation(patient):
    pid = patient.get("/api/patients/me").json()["id"]
    bad = patient.post(f"/api/patients/{pid}/documents", files={"file": ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert bad.status_code == 415
    fake_pdf = patient.post(f"/api/patients/{pid}/documents", files={"file": ("x.pdf", io.BytesIO(b"<html>not a pdf</html>"), "application/pdf")})
    assert fake_pdf.status_code == 415
    html_as_txt = patient.post(f"/api/patients/{pid}/documents", files={"file": ("x.txt", io.BytesIO(b"\x00\x01binary"), "text/plain")})
    assert html_as_txt.status_code == 415
    big = patient.post(f"/api/patients/{pid}/documents", files={"file": ("big.txt", io.BytesIO(b"a" * (5 * 1024 * 1024 + 10)), "text/plain")})
    assert big.status_code == 413
    png = patient.post(f"/api/patients/{pid}/documents", files={"file": ("scan.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 50), "image/png")}, data={"notes": "patient has asthma"})
    assert png.status_code == 201 and png.json()["textExtracted"] is False and png.json()["conditions"] == ["Asthma / COPD"]   # notes are analysed for images


def test_pdf_text_extraction(patient):
    from pypdf import PdfWriter
    pid = patient.get("/api/patients/me").json()["id"]
    w = PdfWriter(); w.add_blank_page(200, 200)
    buf = io.BytesIO(); w.write(buf)
    r = patient.post(f"/api/patients/{pid}/documents", files={"file": ("blank.pdf", io.BytesIO(buf.getvalue()), "application/pdf")})
    assert r.status_code == 201 and r.json()["textExtracted"] is False        # blank/scanned PDF: honest 'no text found'


# ------------------------------------------------------------------------- rooms
def test_rooms_flow_across_roles(admin, reception, patient):
    r = admin.post("/api/rooms", json={"number": "101", "type": "general"}).json()
    assert admin.post("/api/rooms", json={"number": "101"}).status_code == 409
    reception.post("/api/patients", json={"name": "Bed Bob", "age": 50, "phone": "+8801900000050", "gender": "male", "bloodType": "A+", "address": "x"})
    pid = reception.get("/api/patients").json()[0]["id"]
    booked = reception.post(f"/api/rooms/{r['id']}/book", json={"patientId": int(pid)})
    assert booked.json()["status"] == "occupied" and booked.json()["patientName"] == "Bed Bob"
    assert admin.get("/api/rooms").json()[0]["patientName"] == "Bed Bob"                         # admin sees the update
    assert admin.get("/api/stats/admin").json()["inpatients"] == 1
    assert reception.post(f"/api/rooms/{r['id']}/book", json={"patientId": int(pid)}).status_code == 409
    assert reception.post(f"/api/rooms/{r['id']}/empty").json()["status"] == "available"
    assert admin.patch(f"/api/rooms/{r['id']}/type", json={"type": "emergency"}).json()["type"] == "emergency"
    assert reception.delete(f"/api/rooms/{r['id']}").status_code == 403
    assert admin.delete(f"/api/rooms/{r['id']}").status_code == 200 and admin.get("/api/rooms").json() == []


# ------------------------------------------------------------------------- chatbot
def test_chatbot_privacy_emergency_and_rate_limit(admin, reception, patient):
    d = add_doc(admin)
    tomorrow = (today_local() + timedelta(days=1)).isoformat()
    patient.post("/api/appointments/self", json={"doctorId": int(d["id"]), "date": tomorrow, "time": "10:30", "symptoms": "cough"})
    mine = _chat(patient, "when is my next appointment?")
    assert "Dr. Jane Roe" in mine and "10:30" in mine
    assert "10:30" not in _chat(new_client(), "when is my next appointment?")                    # signed-out users never see patient data
    em = _chat(new_client(), "my father is unconscious and not breathing")
    assert "emergency" in em.lower() and "911" in em
    anon = new_client()
    codes = [anon.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code for _ in range(15)]
    assert 429 in codes and codes[0] == 200


def test_stats_reflect_real_data(admin, reception):
    d = add_doc(admin)
    book(reception, d["id"], "fever", "S One", "+8801900000001")
    book(reception, d["id"], "cough", "S Two", "+8801900000002")
    s = admin.get("/api/stats/admin").json()
    assert s["doctors"] == 1 and s["todayAppointments"] == 2 and s["weekly"][-1]["appointments"] == 2 and s["weekly"][-1]["patients"] == 2
    assert s["specialtyCounts"] == {"Cardiology": 1}
    assert new_client().get("/api/public/stats").json()["doctors"] == 1
