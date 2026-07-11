from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth import create_access_token, hash_password, verify_password
from backend.database import get_db
from backend.deps import get_current_user, require_admin
from backend.models import User
from backend.schemas import LoginRequest, TokenResponse, UserCreateRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user.username, user.role)
    return TokenResponse(access_token=token, username=user.username, role=user.role)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/users", response_model=UserResponse)
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    if payload.role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="角色只能是 user 或 admin")
    exists = db.query(User).filter(User.username == payload.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[User]:
    return db.query(User).order_by(User.id.asc()).all()
