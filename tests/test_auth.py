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
    check_login_not_throttled, record_failed_login, clear_failed_logins,
    _failed_logins, _LOGIN_MAX_ATTEMPTS,
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


# ------------------------------------------------------------------ #
#  Login throttling                                                    #
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Module-level state — clear it before and after each test so tests
    can't leak failed-attempt counts into each other."""
    _failed_logins.clear()
    yield
    _failed_logins.clear()


def test_check_login_not_throttled_allows_fresh_email():
    check_login_not_throttled("nobody-tried-this@mikro.local")  # no raise


def test_repeated_failures_trip_the_throttle():
    email = "brute-forced@mikro.local"
    for _ in range(_LOGIN_MAX_ATTEMPTS):
        check_login_not_throttled(email)  # still allowed before this failure
        record_failed_login(email)
    with pytest.raises(HTTPException) as exc_info:
        check_login_not_throttled(email)
    assert exc_info.value.status_code == 429


def test_successful_login_clears_the_throttle():
    email = "recovers@mikro.local"
    for _ in range(_LOGIN_MAX_ATTEMPTS):
        record_failed_login(email)
    clear_failed_logins(email)
    check_login_not_throttled(email)  # no raise — history was wiped


def test_throttle_is_scoped_per_email():
    victim = "victim@mikro.local"
    attacker_target = "someone-else@mikro.local"
    for _ in range(_LOGIN_MAX_ATTEMPTS):
        record_failed_login(victim)
    check_login_not_throttled(attacker_target)  # unaffected by victim's failures


def test_throttle_key_is_case_and_whitespace_insensitive():
    for _ in range(_LOGIN_MAX_ATTEMPTS):
        record_failed_login("Person@Mikro.Local")
    with pytest.raises(HTTPException):
        check_login_not_throttled("  person@mikro.local  ")
