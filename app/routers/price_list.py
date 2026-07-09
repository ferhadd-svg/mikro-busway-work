import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.config import settings
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
async def upload_price_list(file: UploadFile = File(...)):
    """Upload a new price list (.xls or .xlsx). Becomes active immediately."""
    if not file.filename.endswith((".xls", ".xlsx")):
        raise HTTPException(400, "Only .xls or .xlsx files are accepted.")
    dest = settings.price_list_dir / file.filename
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)
    price_list.load(dest)
    return {"message": f"Price list '{file.filename}' loaded successfully."}


@router.post("/activate/{filename}", dependencies=[Depends(require_role("admin"))])
def activate_price_list(filename: str):
    """Switch to a previously uploaded price list file."""
    path = settings.price_list_dir / filename
    if not path.exists():
        raise HTTPException(404, f"File '{filename}' not found.")
    price_list.load(path)
    return {"message": f"'{filename}' is now the active price list."}


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
