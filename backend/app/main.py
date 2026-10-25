"""
main.py - the FastAPI application.

    cd backend
    uvicorn app.main:app --reload            # API on http://127.0.0.1:8000  (docs: /docs in development)

In production the same process also serves the built React frontend (frontend/dist), so one URL = the whole app.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import models  # noqa: F401  (registers all tables)
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Appointment, utcnow
from app.realtime import bus
from app.routers import ai, appointments, auth, chat, doctors, events, meta, patients, rooms, stats
from app.services.priority import model
from app.timeutil import today_local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("helix")


def expire_stale_appointments() -> int:
    """Appointments still 'scheduled' for a day that has passed were never attended -> cancel them so queues stay clean."""
    with SessionLocal() as db:
        n = (db.query(Appointment).filter(Appointment.status == "scheduled", Appointment.date < today_local())
             .update({"status": "cancelled", "cancelled_at": utcnow(), "cancel_reason": "Not attended (expired)"}, synchronize_session=False))
        db.commit()
    if n:
        bus.publish(["appointments", "doctors", "stats"])
    return n


async def _janitor() -> None:
    while True:
        try:
            await run_in_threadpool(expire_stale_appointments)
        except Exception:                                   # never let housekeeping kill the server
            log.exception("janitor failed")
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)                        # creates missing tables (no data is inserted - the system starts empty)
    bus.bind(asyncio.get_running_loop())
    model.load()
    if settings.IS_PROD and settings.OTP_MODE == "demo":
        log.warning("OTP_MODE=demo in production: one-time codes are shown ON SCREEN, so OTP is NOT real two-factor security. "
                    "Fine for a public demo; set OTP_MODE=twilio (and TWILIO_*) before real use.")
    task = asyncio.create_task(_janitor())
    log.info("Helix HMS started (env=%s, db=%s, priority engine=%s)", settings.APP_ENV,
             "sqlite" if settings.is_sqlite else "mysql", model.info["engine"])
    yield
    task.cancel()


app = FastAPI(title="Helix HMS API", version="1.0.0", lifespan=lifespan,
              docs_url=None if settings.IS_PROD else "/docs", redoc_url=None, openapi_url=None if settings.IS_PROD else "/openapi.json")

if settings.CORS_ORIGINS and not settings.IS_PROD:          # only needed when the Vite dev server calls the API cross-origin
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # CSRF guard: every state-changing API call must carry a custom header. A forged cross-site form/link
    # cannot set it (browsers block custom headers cross-origin without CORS approval), so this stops CSRF.
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("x-requested-with") != "helix":
            return JSONResponse({"detail": "Missing X-Requested-With header."}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.IS_PROD:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not request.url.path.startswith(("/docs", "/openapi")):
        response.headers.setdefault("Content-Security-Policy", CSP)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Turn Pydantic's list of errors into ONE readable sentence the UI can show."""
    first = exc.errors()[0]
    field = str(first["loc"][-1]) if first.get("loc") else "input"
    msg = str(first.get("msg", "Invalid value")).replace("Value error, ", "")
    if first.get("type") not in ("value_error",):
        msg = f"{field}: {msg}"
    return JSONResponse({"detail": msg}, status_code=422)


for r in (auth.router, meta.router, doctors.router, patients.router, rooms.router, appointments.router,
          ai.router, stats.router, chat.router, events.router):
    app.include_router(r)


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


# ----------------------------------------------------------------------------- serve the built frontend (single deployment)
DIST = settings.FRONTEND_DIST
if (DIST / "index.html").exists():
    if (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (DIST / full_path).resolve()
        if full_path and candidate.is_file() and DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
else:
    @app.get("/", include_in_schema=False)
    async def no_frontend():
        return JSONResponse({"message": "Helix HMS API is running. The frontend is not built yet - run `npm run build` in /frontend, "
                                        "or start the Vite dev server (`npm run dev`) and open http://localhost:5173"})
