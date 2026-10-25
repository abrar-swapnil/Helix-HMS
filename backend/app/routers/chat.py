"""routers/chat.py - streaming chatbot endpoint (NDJSON lines: meta, delta..., done)."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import ChatIn
from app.security import client_ip, optional_user, rate_limiter
from app.services import chatbot

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/status")
async def chat_status():
    st = await chatbot.ollama_status()
    return {"mode": "ollama" if st["reachable"] and st["modelInstalled"] else "basic", "model": settings.OLLAMA_MODEL}


@router.post("")
async def chat(body: ChatIn, request: Request, user: Optional[User] = Depends(optional_user), db: Session = Depends(get_db)):
    key = f"chat:{user.id if user else client_ip(request)}"
    if not rate_limiter.allow(key, settings.CHAT_RATE_PER_MINUTE):
        raise HTTPException(429, "You're sending messages too quickly. Please wait a moment.")
    history = [{"role": m.role, "content": m.content.strip()} for m in body.messages if m.content.strip()]
    if not history or history[-1]["role"] != "user":
        raise HTTPException(422, "The last message must be from the user.")
    facts = await run_in_threadpool(chatbot.collect_facts, db, user)       # live database snapshot (own data only)

    async def gen():
        async for event in chatbot.stream_reply(facts, history):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
