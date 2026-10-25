"""
Tests the Ollama integration against a FAKE Ollama server that speaks the real HTTP protocol
(GET /api/tags, POST /api/chat with NDJSON streaming). It proves: model detection, streaming, that the live database
(doctors, the signed-in patient's own appointments) is put in the system prompt, the safety notice, auth header,
and graceful fallback when Ollama dies. It cannot judge the quality of a real model's answers.
"""
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import make_patient, new_client
from app.config import settings
from app.services import chatbot
from app.timeutil import today_local


class FakeOllama:
    def __init__(self):
        self.requests = []          # every /api/chat body received
        self.headers = []
        self.mode = "ok"            # ok | die_midstream | error_json
        self.models = ["llama3.2:latest"]
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                outer.headers.append(dict(self.headers))
                body = json.dumps({"models": [{"name": m} for m in outer.models]}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n))
                outer.requests.append(req); outer.headers.append(dict(self.headers))
                self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
                sysmsg = req["messages"][0]["content"]
                if outer.mode == "error_json":
                    self.wfile.write((json.dumps({"error": "model crashed"}) + "\n").encode()); return
                pieces = ["Sure! ", "Based on the hospital data, ", "I can see ", f"{sysmsg.count('| available |')} available doctor(s)."]
                for i, p in enumerate(pieces):
                    self.wfile.write((json.dumps({"message": {"role": "assistant", "content": p}, "done": False}) + "\n").encode()); self.wfile.flush()
                    if outer.mode == "die_midstream" and i == 1:
                        return                                             # connection ends without "done"
                self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n").encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


@pytest.fixture
def ollama(monkeypatch):
    f = FakeOllama()
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", f"http://127.0.0.1:{f.port}")
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3.2")
    chatbot._status_cache.update(at=0.0, value=None)
    yield f
    chatbot._status_cache.update(at=0.0, value=None)
    f.stop()


def chat(client, msg, history=None):
    msgs = (history or []) + [{"role": "user", "content": msg}]
    r = client.post("/api/chat", json={"messages": msgs})
    assert r.status_code == 200, r.text
    ev = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    return ev, "".join(e.get("text", "") for e in ev)


def add_doc(admin, name, email, spec):
    assert admin.post("/api/doctors", json={"name": name, "email": email, "specialty": spec}).status_code == 201


def test_streams_from_ollama_with_live_database_in_prompt(ollama, admin):
    add_doc(admin, "Jane Roe", "j@h.com", "Cardiology")
    ev, text = chat(new_client(), "Which doctors are free?")
    assert ev[0] == {"type": "meta", "mode": "ollama"} and ev[-1] == {"type": "done"}
    assert [e["text"] for e in ev if e["type"] == "delta"][:2] == ["Sure! ", "Based on the hospital data, "]   # arrives piece by piece
    assert "1 available doctor(s)" in text
    sent = ollama.requests[-1]
    assert sent["model"] == "llama3.2" and sent["stream"] is True
    system = sent["messages"][0]
    assert system["role"] == "system" and "Dr. Jane Roe | Cardiology | general | available" in system["content"]   # live DB row, not a copy
    assert "NOT a doctor" in system["content"] and "Never invent doctors" in system["content"]
    assert sent["messages"][-1] == {"role": "user", "content": "Which doctors are free?"}


def test_database_changes_reach_the_prompt_immediately(ollama, admin):
    add_doc(admin, "Jane Roe", "j@h.com", "Cardiology")
    chat(new_client(), "hi")
    assert "Dr. Jane Roe" in ollama.requests[-1]["messages"][0]["content"]
    did = admin.get("/api/doctors").json()[0]["id"]
    admin.patch(f"/api/doctors/{did}/status", json={"status": "unavailable"})
    chat(new_client(), "hi")
    assert "Dr. Jane Roe | Cardiology | general | unavailable" in ollama.requests[-1]["messages"][0]["content"]
    admin.delete(f"/api/doctors/{did}")
    chat(new_client(), "hi")
    assert "Dr. Jane Roe" not in ollama.requests[-1]["messages"][0]["content"]
    assert "none are registered" in ollama.requests[-1]["messages"][0]["content"]


def test_prompt_privacy_signed_out_vs_patient(ollama, admin):
    add_doc(admin, "Jane Roe", "j@h.com", "Cardiology")
    pat, _ = make_patient("pp1", "+8801700000501", "Private Pat", 40)
    did = admin.get("/api/doctors").json()[0]["id"]
    pat.post("/api/appointments/self", json={"doctorId": int(did), "date": (today_local() + timedelta(days=1)).isoformat(), "time": "10:00", "symptoms": "secret rash"})
    chat(new_client(), "hi")
    anon_prompt = ollama.requests[-1]["messages"][0]["content"]
    assert "Private Pat" not in anon_prompt and "secret rash" not in anon_prompt and "10:00" not in anon_prompt
    assert "+8801800" not in anon_prompt and "@h.com" not in anon_prompt                  # no doctor phone / email either
    chat(pat, "when is my appointment?")
    own = ollama.requests[-1]["messages"][0]["content"]
    assert "Private Pat" in own and "10:00 with Dr. Jane Roe" in own and "secret rash" not in own
    other, _ = make_patient("pp2", "+8801700000502", "Other Person", 30)
    chat(other, "when is my appointment?")
    assert "10:00" not in ollama.requests[-1]["messages"][0]["content"]                   # another patient sees none of it


def test_emergency_notice_is_prepended_even_when_the_model_is_used(ollama):
    ev, text = chat(new_client(), "my husband has crushing chest pain and cannot breathe")
    assert text.startswith("⚠️") and "911" in text.split("Sure!")[0] and "Sure!" in text      # fixed safety text first, then the LLM


def test_history_is_trimmed_and_roles_preserved(ollama):
    hist = []
    for i in range(12):
        hist += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]
    chat(new_client(), "latest", hist)
    msgs = ollama.requests[-1]["messages"]
    assert msgs[0]["role"] == "system" and len(msgs) == 1 + 8 and msgs[-1]["content"] == "latest"


def test_falls_back_to_basic_mode_when_model_missing_or_server_down(ollama, admin):
    add_doc(admin, "Jane Roe", "j@h.com", "Cardiology")
    ollama.models = ["some-other-model:latest"]                                           # server up, but our model is not installed
    chatbot._status_cache.update(at=0.0, value=None)
    ev, text = chat(new_client(), "is there a cardiologist?")
    assert ev[0]["mode"] == "basic" and "Dr. Jane Roe" in text and not ollama.requests
    ollama.stop()
    chatbot._status_cache.update(at=0.0, value=None)
    ev, text = chat(new_client(), "is there a cardiologist?")
    assert ev[0]["mode"] == "basic" and "Dr. Jane Roe" in text


def test_ollama_dying_midstream_keeps_the_partial_answer(ollama):
    ollama.mode = "die_midstream"
    ev, text = chat(new_client(), "hello there")
    assert ev[0]["mode"] == "ollama" and "Sure! Based on the hospital data, " in text and ev[-1]["type"] == "done"


def test_model_error_before_any_token_falls_back(ollama, admin):
    add_doc(admin, "Jane Roe", "j@h.com", "Cardiology")
    ollama.mode = "error_json"
    ev, text = chat(new_client(), "is there a cardiologist?")
    assert "Dr. Jane Roe" in text and ev[-1]["type"] == "done"


def test_api_key_is_sent_as_bearer(ollama, monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "tok-123")
    chatbot._status_cache.update(at=0.0, value=None)
    chat(new_client(), "hi")
    assert any(h.get("Authorization") == "Bearer tok-123" for h in ollama.headers)


def test_chat_status_endpoint(ollama):
    assert new_client().get("/api/chat/status").json() == {"mode": "ollama", "model": "llama3.2"}
