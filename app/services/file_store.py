"""
Keep a database copy of files written under data/ so they survive a wiped disk.

The disk stays the working copy (openpyxl, FileResponse and the price-list
loader all want a real path); the database is the durable copy. `save` after
writing a file, `restore` before reading one.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.stored_file import StoredFile

_DIRS = {
    "projects": lambda: settings.projects_dir,
    "price_list": lambda: settings.price_list_dir,
    "templates": lambda: settings.templates_dir,
}


def _dir(kind: str) -> Path:
    return _DIRS[kind]()


def save(db: Session, kind: str, path: Path) -> None:
    """Store (or replace) the database copy of `path`. Commits."""
    data = Path(path).read_bytes()
    row = db.query(StoredFile).filter_by(kind=kind, name=Path(path).name).first()
    if row:
        row.data = data
    else:
        db.add(StoredFile(kind=kind, name=Path(path).name, data=data))
    db.commit()


def restore(db: Session, kind: str, name: str) -> Path | None:
    """Path to the file on disk, writing it back from the database copy if the
    disk was wiped. None if it exists in neither place."""
    path = _dir(kind) / Path(name).name
    if path.exists():
        return path
    row = db.query(StoredFile).filter_by(kind=kind, name=Path(name).name).first()
    if not row:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(row.data)
    return path


def restore_all(db: Session, kind: str) -> int:
    """Write back every stored file of `kind` missing from disk. Returns how
    many were restored."""
    restored = 0
    for (name,) in db.query(StoredFile.name).filter_by(kind=kind).all():
        if not (_dir(kind) / name).exists():
            restore(db, kind, name)
            restored += 1
    return restored
