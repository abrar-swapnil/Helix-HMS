"""routers/events.py - Server-Sent Events: tells every open browser tab "doctors/appointments/... changed, refetch"."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models import User
from app.realtime import bus
from app.security import current_user

router = APIRouter(prefix="/api", tags=["events"])
MAX_LISTENERS = 500


@router.get("/events")
async def events(request: Request, user: User = Depends(current_user)):
    if bus.listeners >= MAX_LISTENERS:
        raise HTTPException(503, "Too many live connections.")
    q = bus.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\nevent: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: changed\ndata: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
