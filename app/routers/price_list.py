from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.services.price_list import price_list

router = APIRouter(prefix="/price-list", tags=["Price List"])


class PriceListInfo(BaseModel):
    loaded: bool
    filename: str | None
    available_files: list[str]


@router.get("/", response_model=PriceListInfo)
def get_price_list_info():
    files = sorted(settings.price_list_dir.glob("*"))
    return PriceListInfo(
        loaded=price_list.is_loaded(),
        filename=Path(price_list.loaded_file()).name if price_list.loaded_file() else None,
        available_files=[
            file.name for file in files if file.suffix.lower() in (".xls", ".xlsx")
        ],
    )


@router.post("/upload", status_code=201)
async def upload_price_list(file: UploadFile = File(...)):
    filename = Path(file.filename or "price-list").name
    if Path(filename).suffix.lower() not in (".xls", ".xlsx"):
        raise HTTPException(400, "Only .xls or .xlsx files are accepted.")

    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(400, "Uploaded price list is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Uploaded price list exceeds the configured size limit.")

    destination = settings.price_list_dir / filename
    destination.write_bytes(content)
    try:
        price_list.load(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "The uploaded spreadsheet is not a valid price list.") from exc
    return {"message": f"Price list '{filename}' loaded successfully."}


@router.post("/activate/{filename}")
def activate_price_list(filename: str):
    safe_filename = Path(filename).name
    if safe_filename != filename:
        raise HTTPException(400, "Invalid filename.")
    path = settings.price_list_dir / safe_filename
    if path.suffix.lower() not in (".xls", ".xlsx") or not path.is_file():
        raise HTTPException(404, f"File '{safe_filename}' not found.")
    price_list.load(path)
    return {"message": f"'{safe_filename}' is now the active price list."}


@router.get("/lookup/feeder")
def lookup_feeder(frame_a: int, earth_pct: int, material: str):
    _require_loaded()
    return {"rate": price_list.feeder(frame_a, earth_pct, material)}


@router.get("/lookup/piu")
def lookup_piu(rating_a: int, ka: int = 26):
    _require_loaded()
    return {"rate": price_list.piu(rating_a, ka)}


def _require_loaded():
    if not price_list.is_loaded():
        raise HTTPException(503, "No price list loaded. Upload one first.")
