"""Mikro Busway Quotation Engine FastAPI application."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine
from app.routers import ai, price_list as price_list_router, projects, salespeople
from app.services.claude_client import is_configured
from app.services.price_list import price_list

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    price_list_files = sorted(
        settings.price_list_dir.glob("*.xls*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if price_list_files:
        price_list.load(price_list_files[0])
        logger.info("Price list loaded file=%s", price_list_files[0].name)
    else:
        logger.warning("No price list found; upload one at POST /price-list/upload")
    logger.info(
        "Application started environment=%s claude_configured=%s",
        settings.app_env,
        is_configured(),
    )
    yield


app = FastAPI(
    title="Mikro Busway Quotation Engine",
    description="Turn an SLD drawing into a BOQ and priced quotation.",
    version="1.3.0",
    lifespan=lifespan,
)

origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(salespeople.router)
app.include_router(projects.router)
app.include_router(price_list_router.router)
app.include_router(ai.router)

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", tags=["UI"])
def ui():
    return FileResponse(str(_static_dir / "index.html"))


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "environment": settings.app_env}


@app.get("/api/status", tags=["Health"])
def api_status():
    return {
        "service": "Mikro Busway Quotation Engine",
        "version": "1.3.0",
        "environment": settings.app_env,
        "claude_configured": is_configured(),
        "claude_model": settings.claude_model,
        "price_list_loaded": price_list.is_loaded(),
        "price_list_file": (
            Path(price_list.loaded_file()).name if price_list.loaded_file() else None
        ),
        "api_docs": "/docs",
    }
