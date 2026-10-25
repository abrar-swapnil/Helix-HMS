"""routers/rooms.py - rooms/beds. Admin creates/removes/retypes rooms; reception admits & discharges patients."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Patient, Room, User
from app.realtime import bus
from app.schemas import RoomBookIn, RoomCreateIn, RoomTypeIn
from app.security import require_roles
from app.services.presenters import rooms_out

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _room(db: Session, room_id: int) -> Room:
    r = db.get(Room, room_id)
    if not r:
        raise HTTPException(404, "Room not found.")
    return r


@router.get("")
def list_rooms(user: User = Depends(require_roles("admin", "receptionist")), db: Session = Depends(get_db)):
    rooms = db.query(Room).options(joinedload(Room.patient)).order_by(Room.number).all()
    return rooms_out(rooms)


@router.post("", status_code=201)
def add_room(body: RoomCreateIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    number = body.number.strip().upper()
    if db.query(Room).filter(Room.number == number).first():
        raise HTTPException(409, f"Room {number} already exists.")
    r = Room(number=number, type=body.type)
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Room {number} already exists.")
    bus.publish(["rooms", "stats"])
    return rooms_out([r])[0]


@router.delete("/{room_id}")
def remove_room(room_id: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    db.delete(_room(db, room_id))
    db.commit()
    bus.publish(["rooms", "stats"])
    return {"ok": True}


@router.patch("/{room_id}/type")
def set_type(room_id: int, body: RoomTypeIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    r = _room(db, room_id)
    r.type = body.type
    db.commit()
    bus.publish(["rooms"])
    return rooms_out([r])[0]


@router.post("/{room_id}/book")
def book_room(room_id: int, body: RoomBookIn, user: User = Depends(require_roles("receptionist")), db: Session = Depends(get_db)):
    r = _room(db, room_id)
    if r.status == "occupied":
        raise HTTPException(409, "This room is already occupied.")
    p = db.get(Patient, body.patient_id)
    if not p:
        raise HTTPException(404, "Patient not found.")
    other = db.query(Room).filter(Room.patient_id == p.id).first()
    if other:
        raise HTTPException(409, f"{p.name} is already in room {other.number}.")
    r.status, r.patient_id = "occupied", p.id
    db.commit()
    bus.publish(["rooms", "stats"])
    return rooms_out([r])[0]


@router.post("/{room_id}/empty")
def empty_room(room_id: int, user: User = Depends(require_roles("receptionist")), db: Session = Depends(get_db)):
    r = _room(db, room_id)
    r.status, r.patient_id = "available", None
    db.commit()
    bus.publish(["rooms", "stats"])
    return rooms_out([r])[0]
