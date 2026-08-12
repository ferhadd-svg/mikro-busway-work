"""
Mikro Busway Quotation Engine — FastAPI backend
Run with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import engine, Base
from app.config import settings
from app.services.price_list import price_list
from app.services.email import email_configured
from app.routers import salespeople, projects, price_list as price_list_router, auth, customers


def _bundled_price_list_source() -> Path | None:
    """The cold-start default price list to seed when none has been uploaded.
    Prefers an explicit PRICE_LIST_BUNDLED_FILE (e.g. a Render Secret File),
    then the newest .xls* committed under app/bundled_price_list/."""
    override = settings.price_list_bundled_file.strip()
    if override:
        p = Path(override)
        if p.is_file():
            return p
        print(f"[startup] PRICE_LIST_BUNDLED_FILE set but not found: {p}")
    if settings.bundled_price_list_dir.is_dir():
        candidates = sorted(
            settings.bundled_price_list_dir.glob("*.xls*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def _load_price_list_on_startup() -> None:
    """Load the most recently uploaded price list. When none exists (e.g. a
    fresh deploy on Render's ephemeral disk), fall back to the bundled default
    so the app always has correct prices — copying it into price_list_dir so it
    shows up in the price-list info/versions UI like a normal file."""
    uploaded = sorted(
        settings.price_list_dir.glob("*.xls*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if uploaded:
        price_list.load(uploaded[0])
        print(f"[startup] Price list loaded: {uploaded[0].name}")
        return

    bundled = _bundled_price_list_source()
    if bundled:
        dest = settings.price_list_dir / f"{time.time_ns()}_{bundled.name}"
        try:
            shutil.copy2(bundled, dest)
            price_list.load(dest)
        except OSError:
            # If the copy fails for any reason, still load directly so prices
            # are available even if the file can't be persisted to the dir.
            price_list.load(bundled)
        print(f"[startup] No uploaded price list — loaded bundled default: {bundled.name}")
        return

    print("[startup] No price list found. Upload one via POST /price-list/upload.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all DB tables
    Base.metadata.create_all(bind=engine)

    _load_price_list_on_startup()

    yield


app = FastAPI(
    title="Mikro Busway Quotation Engine",
    description=(
        "Turn an SLD drawing into a BOQ and priced quotation automatically. "
        "Supports any salesperson including newcomers."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(salespeople.router)
app.include_router(projects.router)
app.include_router(customers.router)
app.include_router(price_list_router.router)

# Serve the browser UI
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", tags=["UI"])
def ui():
    """Browser UI — open this in any web browser."""
    return FileResponse(str(_static_dir / "index.html"))


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.get("/api/status", tags=["Health"])
def api_status():
    return {
        "service": "Mikro Busway Quotation Engine",
        "version": "1.0.0",
        "price_list_loaded": price_list.is_loaded(),
        "price_list_file": Path(price_list.loaded_file()).name if price_list.loaded_file() else None,
        "ai_reader_enabled": bool(settings.anthropic_api_key),  # True once ANTHROPIC_API_KEY is set (value never exposed)
        "email_configured": email_configured(),  # True once SMTP_HOST/SMTP_USER are set (values never exposed)
        "api_docs": "/docs",
    }
