"""Claude API status, authentication test, and general file analysis."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.services.claude_client import (
    SUPPORTED_FILE_SUFFIXES,
    ClaudeConfigurationError,
    ClaudeError,
    ClaudeFileError,
    create_message,
    is_configured,
    ping,
)
from app.services.file_text import SUPPORTED_TEXT_SUFFIXES, extract_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["Claude AI"])
ALL_SUPPORTED_SUFFIXES = SUPPORTED_FILE_SUFFIXES | SUPPORTED_TEXT_SUFFIXES


@router.get("/status")
def ai_status():
    return {
        "configured": is_configured(),
        "model": settings.claude_model,
        "supported_file_types": sorted(ALL_SUPPORTED_SUFFIXES),
    }


@router.post("/test-connection")
def test_connection():
    try:
        result = ping()
    except ClaudeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ClaudeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "status": "connected",
        "model": result["model"],
        "request_id": result["request_id"],
        "response": result["text"],
        "usage": result["usage"],
    }


@router.post("/analyze-file")
async def analyze_file(
    file: UploadFile = File(...),
    prompt: str = Form(
        "Read this file carefully. Extract useful structured information, "
        "including descriptions, ratings, quantities, units, and prices."
    ),
):
    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALL_SUPPORTED_SUFFIXES:
        allowed = ", ".join(sorted(ALL_SUPPORTED_SUFFIXES))
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {allowed}")

    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(400, "Uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"Uploaded file exceeds the {settings.max_upload_bytes}-byte limit.",
        )

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)

        if suffix in SUPPORTED_TEXT_SUFFIXES:
            extracted = await run_in_threadpool(extract_text, temp_path)
            if not extracted.strip():
                raise HTTPException(422, "No readable text was found in the file.")
            full_prompt = f"{prompt.strip()}\n\nExtracted file contents:\n{extracted}"
            result = await run_in_threadpool(create_message, prompt=full_prompt)
        else:
            result = await run_in_threadpool(
                create_message,
                prompt=prompt,
                file_path=temp_path,
            )
    except HTTPException:
        raise
    except ClaudeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ClaudeFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ClaudeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        logger.exception("File analysis preparation failed filename=%s", filename)
        raise HTTPException(422, "The uploaded file could not be read.") from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

    return {
        "filename": filename,
        "model": result["model"],
        "request_id": result["request_id"],
        "usage": result["usage"],
        "analysis": result["text"],
    }
