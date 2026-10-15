"""Shared API authentication dependencies."""
import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_token_subject


PLACEHOLDER_SECRET = "your-secret-key-change-in-production-please"


def ensure_default_user(db: Session) -> int:
    """Ensure the legacy single-user record exists and return its id."""
    from app.models.user import User

    user = db.query(User).filter(User.id == 1).first()
    if not user:
        user = User(
            id=1,
            username="default",
            email="default@example.com",
            hashed_password="$2b$12$dummy_hashed_password_not_for_login",
            is_active=True,
            is_superuser=False,
        )
        db.add(user)
        db.commit()
    return 1


def _resolve_authenticated_user_id(db: Session, authorization: str | None) -> int:
    """Strictly resolve a JWT or full-access service token."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if settings.API_ACCESS_TOKEN and secrets.compare_digest(token, settings.API_ACCESS_TOKEN):
        return ensure_default_user(db)

    try:
        user_id = int(get_token_subject(token))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.models.user import User

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已停用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user.id


def require_current_user_id(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> int:
    """
    Preserve the legacy single-user dashboard for read-only requests.

    Mutating requests still require a valid JWT or API_ACCESS_TOKEN. This lets
    older browser sessions recover from stale credentials without reopening
    unauthenticated strategy start/stop/create operations.
    """
    try:
        return _resolve_authenticated_user_id(db, authorization)
    except HTTPException:
        if request.method.upper() == "GET":
            return ensure_default_user(db)
        raise


def require_mobile_read_user_id(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> int:
    """Allow the scoped mobile token, JWT, or full service token for read-only routes."""
    scheme, _, token = (authorization or "").partition(" ")
    if (
        scheme.lower() == "bearer"
        and token
        and settings.MOBILE_READ_TOKEN
        and secrets.compare_digest(token, settings.MOBILE_READ_TOKEN)
    ):
        return ensure_default_user(db)
    return _resolve_authenticated_user_id(db, authorization)
