"""
Mikro Busway Quotation Engine — FastAPI backend
Run with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import engine, Base
from app.config import settings
from app.services.price_list import price_list
from app.routers import salespeople, projects, price_list as price_list_router, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all DB tables
    Base.metadata.create_all(bind=engine)

    # Auto-load the most recently modified price list on startup
    price_list_files = sorted(
        settings.price_list_dir.glob("*.xls*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if price_list_files:
        price_list.load(price_list_files[0])
        print(f"[startup] Price list loaded: {price_list_files[0].name}")
    else:
        print("[startup] No price list found. Upload one via POST /price-list/upload.")

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
        "api_docs": "/docs",
    }
