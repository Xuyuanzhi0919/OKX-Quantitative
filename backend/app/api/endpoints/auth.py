"""
认证相关API
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import require_current_user_id
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str | None = None
    password: str


@router.post("/login")
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """用户登录，返回JWT访问令牌。"""
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled"
        )

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
        },
    }


@router.post("/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册"""
    exists = db.query(User).filter(User.username == request.username).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already exists"
        )

    if request.email:
        email_exists = db.query(User).filter(User.email == request.email).first()
        if email_exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
            )

    user = User(
        username=request.username,
        email=request.email,
        hashed_password=get_password_hash(request.password),
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
    }


@router.get("/me")
async def get_current_user(
    user_id: int = Depends(require_current_user_id),
    db: Session = Depends(get_db),
):
    """获取当前用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
    }
