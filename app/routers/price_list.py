import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.price_list_version import PriceListVersion
from app.schemas.price_list import PriceListVersionOut, PriceRateOut
from app.services.price_list import price_list
from app.services.auth import get_current_user, require_role

router = APIRouter(prefix="/price-list", tags=["Price List"])


class PriceListInfo(BaseModel):
    loaded: bool
    filename: str | None
    available_files: list[str]


@router.get("/", response_model=PriceListInfo, dependencies=[Depends(get_current_user)])
def get_price_list_info():
    files = sorted(settings.price_list_dir.glob("*"))
    return PriceListInfo(
        loaded=price_list.is_loaded(),
        filename=Path(price_list.loaded_file()).name if price_list.loaded_file() else None,
        available_files=[f.name for f in files if f.suffix in (".xls", ".xlsx")],
    )


@router.post("/upload", status_code=201, dependencies=[Depends(require_role("admin"))])
async def upload_price_list(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a new price list (.xls or .xlsx). Becomes active immediately.
    Saved under a unique, timestamp-prefixed name so re-uploading a file with
    the same name (the normal workflow) never overwrites a previous
    version's bytes — each upload is tracked as its own PriceListVersion,
    so admins can browse history and roll back."""
    if not file.filename.endswith((".xls", ".xlsx")):
        raise HTTPException(400, "Only .xls or .xlsx files are accepted.")

    # time_ns (not time.time()'s 1-second resolution) so two uploads within
    # the same second — e.g. a double-click — never collide on this unique
    # on-disk name.
    stored_filename = f"{time.time_ns()}_{file.filename}"
    dest = settings.price_list_dir / stored_filename
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    price_list.load(dest)
    row_count = (
        len(price_list._al) + len(price_list._cu)
        + len(price_list._piu) + len(price_list._bimetal)
    )

    db.query(PriceListVersion).filter(PriceListVersion.is_active == True).update(
        {"is_active": False}
    )
    db.add(PriceListVersion(
        stored_filename=stored_filename,
        original_filename=file.filename,
        uploaded_by_id=current_user.id,
        is_active=True,
        row_count=row_count,
    ))
    db.commit()

    return {"message": f"Price list '{file.filename}' loaded successfully.", "row_count": row_count}


@router.post("/activate/{filename}", dependencies=[Depends(require_role("admin"))])
def activate_price_list(filename: str):
    """Switch to a previously uploaded price list file. Unreachable from the
    UI (superseded by /versions/{id}/reactivate below) — left in place as a
    harmless legacy path for direct API use."""
    path = settings.price_list_dir / filename
    if not path.exists():
        raise HTTPException(404, f"File '{filename}' not found.")
    price_list.load(path)
    return {"message": f"'{filename}' is now the active price list."}


@router.get("/versions", response_model=list[PriceListVersionOut], dependencies=[Depends(get_current_user)])
def list_price_list_versions(db: Session = Depends(get_db)):
    versions = db.query(PriceListVersion).order_by(PriceListVersion.uploaded_at.desc()).all()
    user_names = dict(db.query(User.id, User.name).all())
    out = []
    for v in versions:
        vo = PriceListVersionOut.model_validate(v)
        vo.uploaded_by_name = user_names.get(v.uploaded_by_id)
        out.append(vo)
    return out


@router.post("/versions/{version_id}/reactivate", dependencies=[Depends(require_role("admin"))])
def reactivate_price_list_version(version_id: int, db: Session = Depends(get_db)):
    version = db.get(PriceListVersion, version_id)
    if not version:
        raise HTTPException(404, f"Price list version {version_id} not found.")
    path = settings.price_list_dir / version.stored_filename
    if not path.exists():
        raise HTTPException(404, f"File '{version.stored_filename}' missing from disk.")

    price_list.load(path)

    db.query(PriceListVersion).filter(PriceListVersion.is_active == True).update(
        {"is_active": False}
    )
    version.is_active = True
    db.commit()

    return {"message": f"'{version.original_filename}' reactivated.", "row_count": version.row_count}


@router.get("/rates", response_model=list[PriceRateOut], dependencies=[Depends(get_current_user)])
def list_price_list_rates():
    _require_loaded()
    return price_list.all_rates()


@router.get("/lookup/feeder", dependencies=[Depends(get_current_user)])
def lookup_feeder(frame_a: int, earth_pct: int, material: str):
    _require_loaded()
    return {"rate": price_list.feeder(frame_a, earth_pct, material)}


@router.get("/lookup/piu", dependencies=[Depends(get_current_user)])
def lookup_piu(rating_a: int, ka: int = 26):
    _require_loaded()
    return {"rate": price_list.piu(rating_a, ka)}


def _require_loaded():
    if not price_list.is_loaded():
        raise HTTPException(503, "No price list loaded. Upload one via POST /price-list/upload.")
