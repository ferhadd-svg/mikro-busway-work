from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.user import User
from app.schemas.user import (
    LoginRequest, UserOut, ChangePasswordRequest, UserCreate, UserUpdate,
    AdminPasswordReset,
)
from app.services.auth import (
    hash_password, verify_password, create_session, delete_session,
    get_current_user, require_role,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=UserOut)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password.")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated.")

    session = create_session(db, user)
    response.set_cookie(
        settings.session_cookie_name,
        session.id,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_lifetime_days * 86400,
        path="/",
    )
    return user


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        delete_session(db, session_id)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"message": "Logged out."}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect.")
    user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"message": "Password changed."}


# ------------------------------------------------------------------ #
#  User management (admin only)                                       #
# ------------------------------------------------------------------ #

@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_role("admin"))])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at).all()


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(require_role("admin"))])
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, f"An account with email '{data.email}' already exists.")
    user = User(
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    updates = data.model_dump(exclude_none=True)
    if "email" in updates and updates["email"] != user.email:
        existing = db.query(User).filter(User.email == updates["email"]).first()
        if existing:
            raise HTTPException(400, f"An account with email '{updates['email']}' already exists.")
    for field, value in updates.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
def reset_user_password(user_id: int, data: AdminPasswordReset, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    user.hashed_password = hash_password(data.new_password)
    db.commit()
    db.refresh(user)
    return user
