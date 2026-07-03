"""
Project workflow:
  1. POST /projects                       — create project record
  2. POST /projects/{id}/drawing          — upload SLD, Claude reads it
  3. GET  /projects/{id}/flags            — get list of flagged items needing answers
  4. POST /projects/{id}/flags            — submit flag answers (LME, earth%, etc.)
  5. POST /projects/{id}/generate-boq     — produce BOQ Excel
  6. POST /projects/{id}/generate-quotation — produce quotation Excel
  7. GET  /projects/{id}/download/boq     — download BOQ file
  8. GET  /projects/{id}/download/quotation — download quotation file
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.salesperson import Salesperson
from app.schemas.project import ProjectCreate, ProjectOut
from app.schemas.boq import DrawingExtraction, FlagAnswers, BOQResponse
from app.services.drawing_reader import read_drawing
from app.services.claude_client import (
    ClaudeConfigurationError,
    ClaudeError,
    ClaudeFileError,
)
from app.services.price_list import price_list
from app.services.boq_builder import build_boq
from app.services.quotation_builder import build_quotation
from app.config import settings

router = APIRouter(prefix="/projects", tags=["Projects"])
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  CRUD                                                               #
# ------------------------------------------------------------------ #

@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.post("/", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.our_ref == data.our_ref).first()
    if existing:
        raise HTTPException(400, f"Project ref '{data.our_ref}' already exists.")
    project = Project(**data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    # Create per-project folder
    _project_dir(project.id).mkdir(parents=True, exist_ok=True)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _get_or_404(project_id, db)


# ------------------------------------------------------------------ #
#  Step 2 — Upload drawing and have Claude read it                    #
# ------------------------------------------------------------------ #

@router.post("/{project_id}/drawing")
async def upload_drawing(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    project = _get_or_404(project_id, db)

    allowed = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")
    filename = Path(file.filename or "drawing").name
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {', '.join(allowed)}")

    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(400, "Uploaded drawing is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Uploaded drawing exceeds the configured size limit.")

    drawing_path = _project_dir(project_id) / filename
    drawing_path.write_bytes(content)

    project.drawing_filename = filename
    project.status = "reading_drawing"
    db.commit()

    try:
        extraction: DrawingExtraction = await run_in_threadpool(
            read_drawing, drawing_path
        )
    except ClaudeConfigurationError as exc:
        project.status = "draft"
        db.commit()
        raise HTTPException(503, str(exc)) from exc
    except ClaudeFileError as exc:
        project.status = "draft"
        db.commit()
        raise HTTPException(400, str(exc)) from exc
    except ClaudeError as exc:
        project.status = "draft"
        db.commit()
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        project.status = "draft"
        db.commit()
        logger.exception("Unexpected drawing read failure project_id=%s", project_id)
        raise HTTPException(500, "Drawing read failed unexpectedly.") from exc

    project.drawing_extraction_json = extraction.model_dump_json()
    project.status = "flags_pending"
    db.commit()

    # Build flags list for the user
    flags_summary = _build_flags_summary(extraction)

    return {
        "project_id": project_id,
        "status": "flags_pending",
        "runs_found": len(extraction.runs),
        "flags": flags_summary,
        "extraction": extraction.model_dump(),
    }


# ------------------------------------------------------------------ #
#  Step 2 (alt) — Manual run entry (no API key required)             #
# ------------------------------------------------------------------ #

@router.post("/{project_id}/runs/manual")
def submit_runs_manually(
    project_id: int,
    runs: list[dict],
    db: Session = Depends(get_db),
):
    """
    Submit busway run data manually (no drawing / no Claude needed).
    Each run must include: run_id, run_type, rating_a, material, earth_pct,
    routing, length_m, piu_ratings. frame_rating_a is computed automatically.
    """
    from app.services.price_list import resolve_frame_rating
    from app.schemas.boq import BusRun

    project = _get_or_404(project_id, db)

    validated_runs = []
    for i, r in enumerate(runs):
        r.setdefault("run_id", f"RUN-{i+1}")
        r.setdefault("frame_rating_a", resolve_frame_rating(r.get("rating_a", 200)))
        r.setdefault("needs_bimetal", r.get("material", "AL") == "AL")
        r.setdefault("flags", [])
        r.setdefault("piu_ratings", [])
        r.setdefault("spare_openings", 0)
        r.setdefault("phases", "3P4W")
        r.setdefault("hanger_spacing_m", 1.5)
        validated_runs.append(BusRun(**r))

    extraction = DrawingExtraction(
        runs=validated_runs,
        global_flags=["Runs entered manually — no drawing uploaded."],
        raw_notes="Manual entry",
    )
    project.drawing_extraction_json = extraction.model_dump_json()
    project.status = "flags_pending"
    db.commit()

    return {
        "project_id": project_id,
        "status": "flags_pending",
        "runs_found": len(validated_runs),
        "flags": _build_flags_summary(extraction),
        "extraction": extraction.model_dump(),
    }


# ------------------------------------------------------------------ #
#  Step 3 — Get flags                                                 #
# ------------------------------------------------------------------ #

@router.get("/{project_id}/flags")
def get_flags(project_id: int, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    if not project.drawing_extraction_json:
        raise HTTPException(400, "No drawing has been uploaded and read for this project yet.")
    extraction = DrawingExtraction.model_validate_json(project.drawing_extraction_json)
    return {
        "project_id": project_id,
        "status": project.status,
        "flags": _build_flags_summary(extraction),
        "runs": [
            {
                "run_id": r.run_id,
                "routing": r.routing,
                "run_type": r.run_type,
                "material": r.material,
                "rating_a": r.rating_a,
                "frame_rating_a": r.frame_rating_a,
                "earth_pct": r.earth_pct,
                "length_m": r.length_m,
                "piu_ratings": r.piu_ratings,
                "flags": r.flags,
            }
            for r in extraction.runs
        ],
    }


# ------------------------------------------------------------------ #
#  Step 4 — Submit flag answers                                       #
# ------------------------------------------------------------------ #

@router.post("/{project_id}/flags")
def submit_flags(project_id: int, answers: FlagAnswers, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    if project.status not in ("flags_pending", "flags_confirmed"):
        raise HTTPException(400, f"Project is in status '{project.status}'. Upload a drawing first.")

    project.flags_json = answers.model_dump_json()
    project.lme_usd_per_mt = answers.lme_usd_per_mt
    project.usd_to_myr = answers.usd_to_myr
    project.status = "flags_confirmed"
    db.commit()

    return {"project_id": project_id, "status": "flags_confirmed", "message": "Flag answers saved."}


# ------------------------------------------------------------------ #
#  Step 5 — Generate BOQ                                              #
# ------------------------------------------------------------------ #

@router.post("/{project_id}/generate-boq", response_model=BOQResponse)
def generate_boq(project_id: int, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    _require_status(project, ("flags_confirmed", "boq_ready", "quotation_ready"))
    _require_price_list()

    extraction = DrawingExtraction.model_validate_json(project.drawing_extraction_json)
    flags = FlagAnswers.model_validate_json(project.flags_json)

    result = build_boq(extraction, flags, project.our_ref, project.client_name)

    project.boq_filename = Path(result.boq_file).name
    project.status = "boq_ready"
    db.commit()

    return result


# ------------------------------------------------------------------ #
#  Step 6 — Generate Quotation                                        #
# ------------------------------------------------------------------ #

@router.post("/{project_id}/generate-quotation")
def generate_quotation(project_id: int, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    _require_status(project, ("boq_ready", "quotation_ready"))
    _require_price_list()

    if not project.salesperson_id:
        raise HTTPException(400, "Project has no salesperson assigned. Update the project first.")

    salesperson = db.get(Salesperson, project.salesperson_id)
    if not salesperson:
        raise HTTPException(400, "Assigned salesperson not found in database.")

    extraction = DrawingExtraction.model_validate_json(project.drawing_extraction_json)
    flags = FlagAnswers.model_validate_json(project.flags_json)

    # Re-build BOQ runs (reuse boq_builder logic without writing Excel again)
    from app.services.boq_builder import build_boq as _build_boq
    boq = _build_boq(extraction, flags, project.our_ref, project.client_name)

    # Look for a salesperson template
    template_candidates = list(settings.templates_dir.glob(f"*{salesperson.name.split()[0].upper()}*"))
    template_path = template_candidates[0] if template_candidates else None

    out_path = build_quotation(
        runs=boq.runs,
        flags=flags,
        salesperson=salesperson,
        our_ref=project.our_ref,
        client_name=project.client_name,
        attn=project.attn,
        me_consultant=project.me_consultant,
        template_path=template_path,
    )

    project.quotation_filename = out_path.name
    project.status = "quotation_ready"
    db.commit()

    return {
        "project_id": project_id,
        "status": "quotation_ready",
        "quotation_file": out_path.name,
        "grand_total_myr": round(boq.subtotal_myr * 1.10),
        "subtotal_myr": round(boq.subtotal_myr),
    }


# ------------------------------------------------------------------ #
#  Step 7 — Download files                                            #
# ------------------------------------------------------------------ #

@router.get("/{project_id}/download/boq")
def download_boq(project_id: int, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    if not project.boq_filename:
        raise HTTPException(404, "BOQ not generated yet.")
    path = settings.projects_dir / project.boq_filename
    if not path.exists():
        raise HTTPException(404, "BOQ file missing from disk.")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=project.boq_filename,
    )


@router.get("/{project_id}/download/quotation")
def download_quotation(project_id: int, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    if not project.quotation_filename:
        raise HTTPException(404, "Quotation not generated yet.")
    path = settings.projects_dir / project.quotation_filename
    if not path.exists():
        raise HTTPException(404, "Quotation file missing from disk.")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=project.quotation_filename,
    )


# ------------------------------------------------------------------ #
#  Salesperson assignment                                             #
# ------------------------------------------------------------------ #

@router.patch("/{project_id}/assign-salesperson/{sp_id}", response_model=ProjectOut)
def assign_salesperson(project_id: int, sp_id: int, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    sp = db.get(Salesperson, sp_id)
    if not sp:
        raise HTTPException(404, "Salesperson not found.")
    project.salesperson_id = sp_id
    db.commit()
    db.refresh(project)
    return project


# ------------------------------------------------------------------ #
#  Upload salesperson quotation template                              #
# ------------------------------------------------------------------ #

@router.post("/templates/upload")
async def upload_template(file: UploadFile = File(...)):
    filename = Path(file.filename or "template").name
    if Path(filename).suffix.lower() not in (".xlsx", ".xls"):
        raise HTTPException(400, "Only .xlsx or .xls templates accepted.")
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(400, "Uploaded template is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Uploaded template exceeds the configured size limit.")
    dest = settings.templates_dir / filename
    dest.write_bytes(content)
    return {"message": f"Template '{filename}' uploaded.", "path": str(dest)}


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def _get_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found.")
    return project


def _project_dir(project_id: int) -> Path:
    return settings.projects_dir / str(project_id)


def _require_status(project: Project, allowed: tuple):
    if project.status not in allowed:
        raise HTTPException(
            400,
            f"Project is in status '{project.status}'. "
            f"Required: {' or '.join(allowed)}.",
        )


def _require_price_list():
    if not price_list.is_loaded():
        raise HTTPException(
            503,
            "No price list loaded. Upload one via POST /price-list/upload first.",
        )


def _build_flags_summary(extraction: DrawingExtraction) -> list[dict]:
    flags = []
    # Global flags
    for f in extraction.global_flags:
        flags.append({"scope": "global", "message": f})
    # Per-run flags
    for run in extraction.runs:
        for f in run.flags:
            flags.append({"scope": run.run_id, "run_routing": run.routing, "message": f})
    # Always flag LME since it must be reconfirmed
    flags.insert(0, {
        "scope": "global",
        "message": "LME rate (USD/MT) and USD→MYR exchange rate must be confirmed before pricing.",
        "required": True,
    })
    return flags
