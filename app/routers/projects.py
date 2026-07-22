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
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.salesperson import Salesperson
from app.models.customer_contact import CustomerContact
from app.models.customer_note import CustomerNote
from app.schemas.project import (
    ProjectCreate, ProjectOut, ProjectUpdate, ProjectOutcomeUpdate,
    EmailQuotationRequest, DrawingReadRequest,
)
from app.schemas.boq import DrawingExtraction, FlagAnswers, BOQResponse
from app.services.drawing_reader import read_drawing, pdf_page_thumbnails
from app.services.price_list import price_list
from app.services.boq_builder import build_boq
from app.services.quotation_builder import build_quotation
from app.services.auth import get_current_user, require_role
from app.services.customers import get_or_create_customer
from app.services.projects import apply_outcome
from app.services.email import send_quotation_email, email_configured
from app.config import settings

# Every endpoint in this router requires a logged-in user (any role) — see
# the note in generate_quotation()/etc. below on the one exception (template
# upload, which is admin-only).
router = APIRouter(prefix="/projects", tags=["Projects"], dependencies=[Depends(get_current_user)])


# ------------------------------------------------------------------ #
#  CRUD                                                               #
# ------------------------------------------------------------------ #

def _enrich_projects(projects: list[Project], db: Session) -> list[ProjectOut]:
    """Shared salesperson_name enrichment — also used by
    app/routers/customers.py's customer-detail endpoint so the two never
    drift into different project-summary shapes."""
    sp_names = dict(db.query(Salesperson.id, Salesperson.name).all())
    out = []
    for p in projects:
        po = ProjectOut.model_validate(p)
        po.salesperson_name = sp_names.get(p.salesperson_id)
        out.append(po)
    return out


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return _enrich_projects(projects, db)


@router.post("/", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.our_ref == data.our_ref).first()
    if existing:
        raise HTTPException(400, f"Project ref '{data.our_ref}' already exists.")
    customer = get_or_create_customer(db, data.client_name, data.attn)
    project = Project(**data.model_dump(), customer_id=customer.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    # Create per-project folder
    _project_dir(project.id).mkdir(parents=True, exist_ok=True)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _get_or_404(project_id, db)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    """Correct Step 1 details after the project exists (typo'd ref, wrong
    client/salesperson). Only the supplied fields change."""
    project = _get_or_404(project_id, db)
    fields = data.model_dump(exclude_unset=True)

    new_ref = fields.get("our_ref")
    if new_ref and new_ref != project.our_ref:
        clash = db.query(Project).filter(
            Project.our_ref == new_ref, Project.id != project_id
        ).first()
        if clash:
            raise HTTPException(400, f"Project ref '{new_ref}' already exists.")

    for key, value in fields.items():
        setattr(project, key, value)

    # Keep the customer link in step with an edited client name.
    if fields.get("client_name"):
        customer = get_or_create_customer(db, project.client_name, project.attn)
        project.customer_id = customer.id

    db.commit()
    return _enrich_projects([project], db)[0]


# ------------------------------------------------------------------ #
#  Step 2 — Upload drawing and have Claude read it                    #
# ------------------------------------------------------------------ #

_ALLOWED_DRAWING = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")


async def _save_uploaded_drawing(project: Project, file: UploadFile) -> Path:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_DRAWING:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {', '.join(_ALLOWED_DRAWING)}")
    drawing_path = _project_dir(project.id) / file.filename
    with open(drawing_path, "wb") as f:
        f.write(await file.read())
    project.drawing_filename = file.filename
    return drawing_path


def _read_and_store(project: Project, drawing_path: Path, pages: list[int] | None, db: Session) -> dict:
    project.status = "reading_drawing"
    db.commit()
    try:
        extraction: DrawingExtraction = read_drawing(drawing_path, pages=pages)
    except Exception as e:
        project.status = "draft"
        db.commit()
        raise HTTPException(500, str(e))
    project.drawing_extraction_json = extraction.model_dump_json()
    project.status = "flags_pending"
    db.commit()
    return {
        "project_id": project.id,
        "status": "flags_pending",
        "runs_found": len(extraction.runs),
        "flags": _build_flags_summary(extraction),
        "extraction": extraction.model_dump(),
    }


@router.post("/{project_id}/drawing/preview")
async def preview_drawing(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Save the uploaded drawing and, for multi-page PDFs, return page
    thumbnails so the user can pick which sheet holds the busduct SLD. Does
    NOT call the AI."""
    project = _get_or_404(project_id, db)
    drawing_path = await _save_uploaded_drawing(project, file)
    db.commit()
    if drawing_path.suffix.lower() == ".pdf":
        page_count, thumbnails = pdf_page_thumbnails(drawing_path)
    else:
        page_count, thumbnails = 1, []
    return {
        "project_id": project_id,
        "filename": project.drawing_filename,
        "page_count": page_count,
        "thumbnails": thumbnails,   # data URLs, empty for single images
    }


@router.post("/{project_id}/drawing/read")
def read_saved_drawing(project_id: int, data: DrawingReadRequest, db: Session = Depends(get_db)):
    """Run the AI read on the already-previewed drawing for the chosen pages."""
    project = _get_or_404(project_id, db)
    if not project.drawing_filename:
        raise HTTPException(400, "No drawing uploaded yet — upload one first.")
    drawing_path = _project_dir(project_id) / project.drawing_filename
    if not drawing_path.exists():
        raise HTTPException(404, "Uploaded drawing file is missing — please re-upload.")
    return _read_and_store(project, drawing_path, data.pages, db)


@router.post("/{project_id}/drawing")
async def upload_drawing(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Single-call upload+read (kept for images / direct use). The wizard uses
    preview + read so it can offer a page picker."""
    project = _get_or_404(project_id, db)
    drawing_path = await _save_uploaded_drawing(project, file)
    return _read_and_store(project, drawing_path, None, db)


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
    project.quoted_value_myr = round(boq.subtotal_myr * 1.10)
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
#  Outcome — win/loss tracking, only settable once quotation_ready    #
# ------------------------------------------------------------------ #

@router.patch("/{project_id}/outcome", response_model=ProjectOut)
def set_project_outcome(project_id: int, data: ProjectOutcomeUpdate, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    _require_status(project, ("quotation_ready",))
    apply_outcome(project, data)
    db.commit()
    return _enrich_projects([project], db)[0]


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
#  Email the quotation                                                #
# ------------------------------------------------------------------ #

@router.get("/{project_id}/email-recipients")
def get_email_recipients(project_id: int, db: Session = Depends(get_db)):
    """Suggested recipients so the UI can prefill the To field — ProjectOut
    carries no emails. Primary contact is returned first (ordered)."""
    project = _get_or_404(project_id, db)
    sp = db.get(Salesperson, project.salesperson_id) if project.salesperson_id else None
    contacts = []
    if project.customer_id:
        rows = (
            db.query(CustomerContact)
            .filter(CustomerContact.customer_id == project.customer_id)
            .order_by(CustomerContact.is_primary.desc())
            .all()
        )
        contacts = [
            {"name": c.name, "email": c.email, "is_primary": c.is_primary}
            for c in rows if c.email
        ]
    return {
        "email_configured": email_configured(),
        "salesperson_email": sp.email if sp and sp.email else None,
        "contacts": contacts,
    }


@router.post("/{project_id}/email-quotation")
def email_quotation(project_id: int, data: EmailQuotationRequest, db: Session = Depends(get_db)):
    project = _get_or_404(project_id, db)
    _require_status(project, ("quotation_ready",))
    if not project.quotation_filename:
        raise HTTPException(404, "Quotation not generated yet.")
    path = settings.projects_dir / project.quotation_filename
    if not path.exists():
        raise HTTPException(404, "Quotation file missing from disk.")
    if not data.to:
        raise HTTPException(400, "At least one recipient is required.")

    to = [str(x) for x in data.to]
    cc = [str(x) for x in data.cc]
    subject = data.subject or f"Quotation {project.our_ref} — {project.client_name}"
    body = data.message or (
        f"Dear Sir/Madam,\n\nPlease find attached our quotation "
        f"{project.our_ref} for {project.client_name}.\n\nThank you."
    )

    try:
        send_quotation_email(to, cc, subject, body, path)
    except RuntimeError as e:      # not configured
        raise HTTPException(400, str(e))
    except Exception as e:         # SMTP / send failure
        raise HTTPException(502, f"Failed to send email: {e}")

    # Audit trail on the customer's append-only activity log (Phase 3).
    if project.customer_id:
        db.add(CustomerNote(
            customer_id=project.customer_id,
            author_id=None,
            body=f"Quotation {project.our_ref} emailed to {', '.join(to)}",
        ))
        db.commit()

    return {"status": "sent", "to": to}


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

@router.post("/templates/upload", dependencies=[Depends(require_role("admin"))])
async def upload_template(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx or .xls templates accepted.")
    dest = settings.templates_dir / file.filename
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"message": f"Template '{file.filename}' uploaded.", "path": str(dest)}


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
