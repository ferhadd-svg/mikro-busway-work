from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.salesperson import Salesperson
from app.schemas.salesperson import SalespersonCreate, SalespersonUpdate, SalespersonOut
from app.services.auth import get_current_user, require_role

router = APIRouter(prefix="/salespeople", tags=["Salespeople"])


@router.get("/", response_model=list[SalespersonOut], dependencies=[Depends(get_current_user)])
def list_salespeople(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Salesperson)
    if active_only:
        q = q.filter(Salesperson.is_active == True)
    return q.all()


@router.post("/", response_model=SalespersonOut, status_code=201, dependencies=[Depends(require_role("admin"))])
def create_salesperson(data: SalespersonCreate, db: Session = Depends(get_db)):
    existing = db.query(Salesperson).filter(Salesperson.name == data.name).first()
    if existing:
        raise HTTPException(400, f"Salesperson '{data.name}' already exists.")
    sp = Salesperson(**data.model_dump())
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return sp


@router.get("/{sp_id}", response_model=SalespersonOut, dependencies=[Depends(get_current_user)])
def get_salesperson(sp_id: int, db: Session = Depends(get_db)):
    sp = db.get(Salesperson, sp_id)
    if not sp:
        raise HTTPException(404, "Salesperson not found.")
    return sp


@router.patch("/{sp_id}", response_model=SalespersonOut, dependencies=[Depends(require_role("admin"))])
def update_salesperson(sp_id: int, data: SalespersonUpdate, db: Session = Depends(get_db)):
    sp = db.get(Salesperson, sp_id)
    if not sp:
        raise HTTPException(404, "Salesperson not found.")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(sp, field, value)
    db.commit()
    db.refresh(sp)
    return sp


@router.delete("/{sp_id}", status_code=204, dependencies=[Depends(require_role("admin"))])
def delete_salesperson(sp_id: int, db: Session = Depends(get_db)):
    sp = db.get(Salesperson, sp_id)
    if not sp:
        raise HTTPException(404, "Salesperson not found.")
    sp.is_active = False
    db.commit()
