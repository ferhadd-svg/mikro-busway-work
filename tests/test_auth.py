import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.user import User
from app.models.session import UserSession
from app.services.auth import (
    hash_password, verify_password, create_session, get_session,
    delete_session, require_role,
)


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _user(db, role="sales", email="test@mikro.local"):
    user = User(email=email, name="Test User", hashed_password=hash_password("hunter22"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ------------------------------------------------------------------ #
#  Password hashing                                                    #
# ------------------------------------------------------------------ #

def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("correct-password")
    assert verify_password("correct-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_produces_different_hash_each_time():
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2
    assert verify_password("same-password", h1)
    assert verify_password("same-password", h2)


# ------------------------------------------------------------------ #
#  Session lifecycle                                                   #
# ------------------------------------------------------------------ #

def test_create_session_generates_unique_ids():
    db = _db()
    user = _user(db)
    s1 = create_session(db, user)
    s2 = create_session(db, user)
    assert s1.id != s2.id
    assert len(s1.id) > 20


def test_get_session_returns_none_for_unknown_id():
    db = _db()
    assert get_session(db, "not-a-real-session-id") is None


def test_get_session_returns_none_for_expired_session():
    db = _db()
    user = _user(db)
    expired = UserSession(
        id="expired-session-token",
        user_id=user.id,
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=20),
        expires_at=datetime.datetime.utcnow() - datetime.timedelta(days=6),
    )
    db.add(expired)
    db.commit()
    assert get_session(db, "expired-session-token") is None


def test_get_session_returns_session_for_valid_id():
    db = _db()
    user = _user(db)
    session = create_session(db, user)
    fetched = get_session(db, session.id)
    assert fetched is not None
    assert fetched.user_id == user.id


def test_delete_session_removes_row_and_is_idempotent():
    db = _db()
    user = _user(db)
    session = create_session(db, user)
    delete_session(db, session.id)
    assert get_session(db, session.id) is None
    delete_session(db, session.id)  # second delete should not raise


# ------------------------------------------------------------------ #
#  Role guard                                                          #
# ------------------------------------------------------------------ #

def test_require_role_allows_matching_role():
    db = _db()
    admin = _user(db, role="admin", email="admin@mikro.local")
    dep = require_role("admin")
    assert dep(user=admin) is admin


def test_require_role_rejects_wrong_role():
    db = _db()
    sales = _user(db, role="sales", email="sales@mikro.local")
    dep = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        dep(user=sales)
    assert exc_info.value.status_code == 403
