"""
Keep a database copy of files written under data/ so they survive a wiped disk.

The disk stays the working copy (openpyxl, FileResponse and the price-list
loader all want a real path); the database is the durable copy. `save` after
writing a file, `restore` before reading one.

`subdir` is one extra folder level under the kind's directory — used for
drawings, which live in projects/<project id>/.
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


def _dir(kind: str, subdir: str = "") -> Path:
    base = _DIRS[kind]()
    return base / Path(subdir).name if subdir else base


def _key(name: str, subdir: str = "") -> str:
    name = Path(name).name
    return f"{Path(subdir).name}/{name}" if subdir else name


def save(db: Session, kind: str, path: Path, subdir: str = "") -> None:
    """Store (or replace) the database copy of `path`. Commits."""
    data = Path(path).read_bytes()
    key = _key(Path(path).name, subdir)
    row = db.query(StoredFile).filter_by(kind=kind, name=key).first()
    if row:
        row.data = data
    else:
        db.add(StoredFile(kind=kind, name=key, data=data))
    db.commit()


def delete_subdir_except(db: Session, kind: str, subdir: str, keep: str) -> None:
    """Drop stored copies in `subdir` other than `keep` — e.g. a project's
    previous drawing once a new one is uploaded, so old drawings don't pile
    up in the database. Commits."""
    prefix = f"{Path(subdir).name}/"
    for row in db.query(StoredFile).filter(
        StoredFile.kind == kind, StoredFile.name.startswith(prefix)
    ).all():
        if row.name != _key(keep, subdir):
            db.delete(row)
    db.commit()


def restore(db: Session, kind: str, name: str, subdir: str = "") -> Path | None:
    """Path to the file on disk, writing it back from the database copy if the
    disk was wiped. None if it exists in neither place."""
    path = _dir(kind, subdir) / Path(name).name
    if path.exists():
        return path
    row = db.query(StoredFile).filter_by(kind=kind, name=_key(name, subdir)).first()
    if not row:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(row.data)
    return path


def restore_all(db: Session, kind: str) -> int:
    """Write back every stored top-level file of `kind` missing from disk.
    Returns how many were restored."""
    restored = 0
    for (name,) in db.query(StoredFile.name).filter_by(kind=kind).all():
        if "/" in name:
            continue
        if not (_dir(kind) / name).exists():
            restore(db, kind, name)
            restored += 1
    return restored
