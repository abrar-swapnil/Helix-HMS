# Helix HMS - AI-assisted Hospital Management System

A web app with four role interfaces (**Admin, Receptionist, Doctor, Patient**) on one shared database, an **XGBoost model that
orders every doctor's queue** by how sick each patient is *and* how long they have waited, and an **Ollama chatbot** that answers
from the live hospital data.

```
 React + Tailwind (your UI)  <-- one URL -->  FastAPI (Python)  <-->  MySQL
   4 role dashboards + landing                  |   auth, rules, live updates (SSE)
   chatbot, records, live queue                 |-- XGBoost priority model  (services/priority.py)
                                                |-- record reader + symptom analyser
                                                '-- Ollama chatbot (local LLM, falls back to basic mode)
```


## Screenshots (from the real running app)
| | |
|---|---|
| ![AI preview](docs/screenshots/09_reception_ai_preview.png) | ![Doctor queue](docs/screenshots/13_doctor_waiting_list.png) |
| Reception: live AI score + suggested specialty while typing | Doctor: waiting list ordered by AI priority, not arrival |
| ![Reassignment](docs/screenshots/20_reception_after_reassign.png) | ![Patient](docs/screenshots/16_patient_records.png) |
| Doctor went away: patients moved to the same specialty | Patient: live roster + medical records |
| ![Chatbot](docs/screenshots/17_patient_chatbot.png) | ![Landing](docs/screenshots/01_landing_empty.png) |
| Chatbot answering from live data (shown in Basic mode) | Fresh install: empty, real numbers |

## What it does

| | |
|---|---|
| **One source of truth** | Everything is stored in MySQL. When anyone adds / edits / removes a doctor, books, cancels, changes status... every open screen of every role - and the chatbot - updates within about a second (Server-Sent Events + refetch). Nothing is hard-coded: a fresh install is **empty** (no fake doctors, patients or numbers). |
| **AI queue** | Each waiting patient gets a priority from an XGBoost model fed with: current symptoms (free text), age, chronic conditions found in the patient's **uploaded medical documents**, and **real-time waiting time**. Doctors see the list sorted by it. Details: [docs/AI_MODEL.md](docs/AI_MODEL.md) |
| **Right specialist** | While symptoms are typed, the AI suggests the matching specialty (one click filters the doctor list). |
| **Doctor away = patients moved** | When a doctor sets "Not Available" (or the admin removes them) their waiting patients move automatically to another doctor of the **same specialty** (least busy first, same department preferred). If there is nobody to take them they stay and are flagged for reception. Patients, reception and the chatbot see the change at once. |
| **Medical records** | Patients (and reception) upload PDF / TXT / PNG / JPG. The AI reads PDF/TXT text (negation-aware: "no history of stroke" is ignored; relatives' diseases are ignored). Treating doctors can view them. Admin cannot. |
| **Chatbot** | Local Ollama model, answers streamed, grounded in live doctors / availability / the patient's own appointments, always shows an emergency notice for danger words. Works without Ollama in "Basic mode". |
| **Login** | Username + password (Argon2 hashed). Admin and patient also confirm a 6-digit OTP. Staff sign-up needs a shared **staff access code** so strangers cannot become admins. |

### Roles
* **Admin** - doctors (add / remove / General-or-Emergency department), rooms, statistics from real data.
* **Receptionist** - register patients, book general / emergency appointments (time slot auto-assigned), admit / discharge rooms, upgrade to emergency, cancel, attach records.
* **Doctor** - own status, AI-ordered waiting list with symptoms + history, "Done", records view, analytics. A doctor the admin added to the roster claims it by registering with the **same email**.
* **Patient** - register + profile, book with a doctor/date/time + symptoms (AI preview), see the queue position, upload records, chat.

## What I changed in your frontend

Your look and layout are unchanged (compared screen by screen against your original). Changes:

* **Removed all mock data** (`mockData.ts`, fake landing-page statistics "4,800+ doctors", the "any credentials work" demo). Landing stats are now real counts.
* **Build config**: your `vite.config.ts` imported a Figma-only file that is not in the zip, so `npm run dev` would crash on your PC. Replaced by a clean config (dev server proxies `/api` to the backend). Removed `AGENTS.md` / `CLAUDE.md` (Figma Make notes).
* **Small additions the features needed** (same styling): patient **profile step** after sign-up (name/age/gender/blood type), **staff access code** field (only shown when the server requires it), OTP screen shows the demo code + *Resend*, **symptoms box** in patient booking, **AI preview panel** (score, what it understood, suggested specialty), **Medical Records** card (patient), *Attach document* + *Records* column (reception), *Records* button + symptoms/history chips (doctor), "Moved from Dr X" badges, queue position for patients, empty-state messages, "Unknown" blood type (instead of silently defaulting to A+), toasts and inline server error messages, chatbot header shows *Basic mode* when Ollama is offline.

## Project layout
```
backend/
  app/main.py              app, security headers, CSRF guard, serves the built frontend
  app/config.py            ALL settings (read from .env)           app/models.py   database tables
  app/security.py          Argon2, session cookie, roles, login lockout
  app/routers/             auth, doctors, patients(+documents), rooms, appointments, ai, stats, chat, events, meta
  app/services/
     triage.py             symptom text -> features, specialty suggestion
     history.py            read documents -> chronic conditions
     priority.py           THE XGBoost model + safety constraints + rule fallback
     queue.py reassign.py  waiting time, ordering, slots, doctor-away logic
     chatbot.py otp.py presenters.py
  app/ml/                  priority_xgb.json (trained model), synth.py, train_priority_model.py
  tests/                   43 tests      .env.example  every setting explained
frontend/                  your React app (src/lib = API client + live sync, src/components = dashboards)
docs/AI_MODEL.md           how the AI works and its honest limits
Dockerfile  docker-compose.yml  render.yaml  .github/workflows/ci.yml
```

---
## 1. Run it on your PC (Windows)

**You need:** Python 3.10+, Node.js 20+, MySQL 8 (you already have it), Git.

**A. Database** - in MySQL Workbench or `mysql -u root -p`:
```sql
CREATE DATABASE helix_hms CHARACTER SET utf8mb4;
CREATE USER 'helix'@'localhost' IDENTIFIED BY 'choose_a_password';
GRANT ALL PRIVILEGES ON helix_hms.* TO 'helix'@'localhost';
```
(Tables are created automatically on first start. No data is inserted.)

**B. Backend** (PowerShell, in the project folder)
```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env             # then open .env and set DATABASE_URL (your MySQL password) 
uvicorn app.main:app --reload
```
Leave this running. It says `Helix HMS started (... db=mysql, priority engine=xgboost)`.
(If it says `rule-based-fallback`, the model file did not load - see `/api/ai/status` as admin.)

**C. Frontend** (a second terminal)
```powershell
cd frontend
npm install
npm run dev
```
Open **http://localhost:5173**.

**D. First use** - there is no seed data on purpose:
1. *Access Portal -> Administrator -> Register* (leave the staff code empty while `STAFF_SIGNUP_CODE` is empty). The OTP screen shows the code; click *Auto-fill*.
2. As admin: add rooms and doctors. 3. Register a Receptionist, a Doctor (use the email the admin entered to claim that roster entry), and a Patient in other browser windows (use a private window per role - one browser = one login).

Single-process mode (what production uses): `cd frontend && npm run build`, then `uvicorn app.main:app` and open **http://localhost:8000**.

### The chatbot (Ollama)
```powershell
# install from https://ollama.com, then:
ollama pull llama3.2
```
Nothing else to configure (`OLLAMA_BASE_URL=http://localhost:11434`). Open the chat; the header says *Online*. Without Ollama it says *Basic mode*. Smaller / bigger model: `OLLAMA_MODEL=qwen2.5:3b` etc.

### Tests
```powershell
cd backend
pip install -r requirements-dev.txt
pytest                              # 43 tests, uses a temporary SQLite file
```
To run them on MySQL use an **empty database whose name contains "test"** (the tests wipe it; the suite refuses otherwise):
`set HELIX_TEST_DATABASE_URL=mysql+pymysql://helix:pw@localhost:3306/helix_test` then `pytest`.

---
## 2. Put it on GitHub
```powershell
cd helix-hms          # the folder that contains backend/ and frontend/
git init
git add .
git status            # check: NO .env file in the list (it is in .gitignore)
git commit -m "Helix HMS"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/helix-hms.git
git push -u origin main
```
Never commit `.env` (passwords, secrets). GitHub Actions (`.github/workflows/ci.yml`) then runs the tests and the frontend build on every push.

---
## 3. Host it so anyone with the link can use it

The app is **one web service** (the Python server also serves the React build) plus **one MySQL database**.

### Option A - Render (app) + Aiven (MySQL), both with free tiers
Free-tier terms change - check their pages. When this was written: Render's free web service **sleeps after 15 minutes without traffic** (the next visit takes up to a minute to wake), has an ephemeral disk (fine - files are stored in MySQL) and a monthly hours limit; Aiven's free MySQL is 1 GB, no card, and may be powered off if unused.

1. **Aiven**: create a free MySQL service. From its page copy the connection details and download the **CA certificate**.
   Your URL becomes `mysql+pymysql://USER:PASSWORD@HOST:PORT/DBNAME` (change the scheme from `mysql://` to `mysql+pymysql://` and drop any `?ssl-mode=...`).
2. **Render**: *New + -> Web Service* -> your GitHub repo -> **Runtime: Docker** -> instance type **Free**. (Or *New + -> Blueprint*; `render.yaml` is included.) Environment variables:

   | Variable | Value |
   |---|---|
   | `APP_ENV` | `production` |
   | `DATABASE_URL` | the URL from step 1 |
   | `DB_SSL_CA_PEM` | the CA certificate text (newlines may be pasted as `\n`) |
   | `JWT_SECRET` | 64 random characters: `python -c "import secrets; print(secrets.token_hex(32))"` |
   | `STAFF_SIGNUP_CODE` | a code only your team/judges know |
   | `HOSPITAL_TIMEZONE`, `EMERGENCY_NUMBER`, ... | see `.env.example` |
3. Deploy. In production the server **refuses to start** without `JWT_SECRET` and `STAFF_SIGNUP_CODE` (so you cannot accidentally publish an app where anyone can register as admin).
4. Share the Render URL. **Before a demo, open it once** to wake it, and check the Aiven service is running.

### Option B - your own server / VPS with Docker
```bash
cp .env.docker.example .env      # edit the passwords; for the internet also set APP_ENV=production, JWT_SECRET, STAFF_SIGNUP_CODE
docker compose up --build        # app on :8000 (+ MySQL). Put HTTPS (Caddy / Nginx / Cloudflare) in front.
```

### The chatbot when hosted
A free host cannot run an LLM. Choices: (1) do nothing - the chatbot runs in **Basic mode** with the same live data; (2) run Ollama on your PC and expose it to the host with a tunnel (e.g. Cloudflare Tunnel), then set `OLLAMA_BASE_URL` on Render; (3) run Ollama on a VPS with enough RAM.
**Warning:** Ollama has no login. Anyone who learns its URL can use your computer's CPU/GPU - keep the URL private or put a password-checking proxy in front (`OLLAMA_API_KEY` is sent as a bearer token). The chat endpoint is rate-limited per user/IP.

---
## Security - what is in place, and what is NOT
In place: Argon2 password hashing, HttpOnly + SameSite session cookie (HTTPS-only in production), login lockout after 5 failures, role checks on **every** endpoint (tested), CSRF header guard, strict Content-Security-Policy and security headers, input validation, upload validation (type + magic bytes, 5 MB, downloaded only as attachments), per-record access rules, rate limits on sign-up / OTP / chat, SQL via the ORM (no string-built SQL), fail-fast production config.

**Not** in place / know before real use:
* **This is a demo / learning project - do not store real patient data in it.** It is not HIPAA/GDPR-compliant: no audit log, no encryption of stored documents beyond what your database host provides, no data-retention or consent features, no password-reset or email verification.
* `OTP_MODE=demo` shows the code on screen, so it is **not** two-factor security. Set `OTP_MODE=twilio` for real SMS (the Twilio call is written but I could not test it without an account).
* The AI model is trained on synthetic data and is **not clinically validated** (see docs/AI_MODEL.md).
* No database migrations: after changing `models.py`, existing tables are not altered (add Alembic, or recreate the DB while developing).
* One server process only (live updates and lockouts are in memory).

## What was and was not tested
**Tested:** 43 automated tests (all four roles, permissions, queue ordering, waiting time, reassignment, documents, chatbot, AI model properties) passing on SQLite, MariaDB 10.11 (MySQL-compatible), MariaDB over TLS, Python 3.10 and 3.12; a clean `pip install` and `npm ci`; the type-check and production build; a real-browser run of the complete 4-role scenario on MariaDB with no console or CSP errors (screens compared with your original); the Ollama integration against a fake server speaking its protocol; memory use about 250 MB.
**Not tested (be careful / test on your side):** answers of a *real* Ollama model; Twilio SMS; Docker, docker-compose and the Render blueprint (no Docker in my environment - the steps they run were checked separately); MySQL 8 itself (I used MariaDB 10.11); Aiven; running on Windows; large-scale load.

## Troubleshooting
* `Access denied for user` - `DATABASE_URL` user/password wrong, or special characters in the password need URL-encoding (`@` -> `%40`).
* `Can't connect to MySQL server` - MySQL service not running (Windows: *Services -> MySQL*).
* Session lost on every refresh in development - `.env` has no `JWT_SECRET`, so a new one is generated at each restart; set one.
* Port 8000 busy - `uvicorn app.main:app --port 8001` (and set `BACKEND_URL=http://127.0.0.1:8001` before `npm run dev`).
* MySQL 5.7 only: uploads fail above 4 MB unless `max_allowed_packet` is raised.
* Wrong "today" / slot times - set `HOSPITAL_TIMEZONE` to your IANA timezone.
