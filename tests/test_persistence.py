"""Persistence across a wiped disk: files backed up in the database, the
Postgres URL handling, and the env-configured admin seed."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.seed as seed
from app.config import settings
from app.database import Base, _normalise_url
from app.models.stored_file import StoredFile
from app.models.user import User
from app.services import file_store
from app.services.auth import verify_password


def _sessionmaker():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


# ------------------------------------------------------------------ #
#  file_store                                                         #
# ------------------------------------------------------------------ #

def test_file_restored_after_disk_wipe(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    db = _sessionmaker()()
    f = tmp_path / "QUOTATION_MK-1.xlsx"
    f.write_bytes(b"quotation bytes")

    file_store.save(db, "projects", f)
    f.unlink()  # simulate the deploy wiping data/

    restored = file_store.restore(db, "projects", "QUOTATION_MK-1.xlsx")
    assert restored == f
    assert f.read_bytes() == b"quotation bytes"


def test_save_replaces_existing_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    db = _sessionmaker()()
    f = tmp_path / "BOQ_MK-1.xlsx"
    f.write_bytes(b"v1")
    file_store.save(db, "projects", f)
    f.write_bytes(b"v2")  # regenerated
    file_store.save(db, "projects", f)

    assert db.query(StoredFile).count() == 1
    f.unlink()
    assert file_store.restore(db, "projects", "BOQ_MK-1.xlsx").read_bytes() == b"v2"


def test_restore_unknown_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    db = _sessionmaker()()
    assert file_store.restore(db, "projects", "nope.xlsx") is None


def test_restore_ignores_directory_components(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    db = _sessionmaker()()
    assert file_store.restore(db, "projects", "../../etc/passwd") is None
    assert not (tmp_path / "etc").exists()


def test_restore_all_only_writes_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "templates_dir", tmp_path)
    db = _sessionmaker()()
    for name in ("Eric.xlsx", "Gladness.xlsx"):
        (tmp_path / name).write_bytes(name.encode())
        file_store.save(db, "templates", tmp_path / name)
    (tmp_path / "Eric.xlsx").unlink()

    assert file_store.restore_all(db, "templates") == 1
    assert (tmp_path / "Eric.xlsx").read_bytes() == b"Eric.xlsx"


# ------------------------------------------------------------------ #
#  DATABASE_URL                                                       #
# ------------------------------------------------------------------ #

def test_postgres_urls_use_psycopg3():
    assert _normalise_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _normalise_url("postgresql://u:p@h/db?sslmode=require") == \
        "postgresql+psycopg://u:p@h/db?sslmode=require"


def test_other_urls_untouched():
    assert _normalise_url("sqlite:///./data/x.db") == "sqlite:///./data/x.db"
    assert _normalise_url("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"


# ------------------------------------------------------------------ #
#  Admin seed                                                         #
# ------------------------------------------------------------------ #

def test_admin_seeded_from_env(monkeypatch, capsys):
    Session = _sessionmaker()
    monkeypatch.setattr(seed, "SessionLocal", Session)
    monkeypatch.setattr(settings, "admin_email", "boss@itmikro.com")
    monkeypatch.setattr(settings, "admin_password", "s3cret-from-env")

    seed.seed_admin_user()

    admin = Session().query(User).one()
    assert admin.email == "boss@itmikro.com"
    assert admin.role == "admin"
    assert verify_password("s3cret-from-env", admin.hashed_password)
    assert "s3cret-from-env" not in capsys.readouterr().out


def test_admin_random_password_when_env_unset(monkeypatch, capsys):
    Session = _sessionmaker()
    monkeypatch.setattr(seed, "SessionLocal", Session)
    monkeypatch.setattr(settings, "admin_password", "")

    seed.seed_admin_user()

    out = capsys.readouterr().out
    printed = next(l for l in out.splitlines() if "password:" in l).split("password:")[1].strip()
    assert verify_password(printed, Session().query(User).one().hashed_password)


def test_admin_not_reseeded_when_users_exist(monkeypatch):
    Session = _sessionmaker()
    monkeypatch.setattr(seed, "SessionLocal", Session)
    monkeypatch.setattr(settings, "admin_password", "x")
    seed.seed_admin_user()
    seed.seed_admin_user()
    assert Session().query(User).count() == 1
