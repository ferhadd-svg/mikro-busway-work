"""
Password hashing and server-side session management.

Sessions are DB-backed: the session id (a secrets.token_urlsafe(32) random
string) is itself the cookie value, looked up against the user_sessions
table on every request. There is nothing to forge by tampering with the
cookie — an attacker without a valid id just gets a DB miss (401). This
means signing (e.g. itsdangerous, JWT) is unnecessary here.
"""

import secrets
import datetime

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.user import User
from app.models.session import UserSession


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_session(db: Session, user: User) -> UserSession:
    now = datetime.datetime.utcnow()
    session = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now,
        expires_at=now + datetime.timedelta(days=settings.session_lifetime_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> UserSession | None:
    session = db.get(UserSession, session_id)
    if session is None:
        return None
    if session.expires_at < datetime.datetime.utcnow():
        return None
    return session


def delete_session(db: Session, session_id: str) -> None:
    session = db.get(UserSession, session_id)
    if session is not None:
        db.delete(session)
        db.commit()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        raise HTTPException(401, "Not logged in.")
    session = get_session(db, session_id)
    if session is None:
        raise HTTPException(401, "Session expired or invalid. Please log in again.")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Account not found or deactivated.")
    return user


def require_role(role: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(403, "Insufficient permissions.")
        return user
    return _dep
