import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session_factory
from models.user import User

logger = logging.getLogger(__name__)

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)

SESSION_COOKIE_NAME = "session"
FLASH_COOKIE_NAME = "flash_messages"


async def get_db():
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


def create_session(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def decode_session(cookie_value: str, max_age: Optional[int] = None) -> Optional[int]:
    if max_age is None:
        max_age = settings.TOKEN_EXPIRY_SECONDS
    try:
        data = serializer.loads(cookie_value, max_age=max_age)
        return data.get("user_id")
    except SignatureExpired:
        logger.warning("Session cookie expired")
        return None
    except BadSignature:
        logger.warning("Invalid session cookie signature")
        return None
    except Exception:
        logger.exception("Unexpected error decoding session cookie")
        return None


def set_session_cookie(response: Response, user_id: int) -> None:
    cookie_value = create_session(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        max_age=settings.TOKEN_EXPIRY_SECONDS,
        path="/",
    )


def destroy_session(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
    )
    response.delete_cookie(
        key=FLASH_COOKIE_NAME,
        path="/",
    )


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = decode_session(cookie_value)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is inactive")

    return user


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Optional[User]:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        return None

    user_id = decode_session(cookie_value)
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        return None

    if not user.is_active:
        return None

    return user


def require_role(allowed_roles: list[str]):
    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


def add_flash(request: Request, response: Response, message: str, category: str = "info") -> None:
    existing_raw = request.cookies.get(FLASH_COOKIE_NAME)
    messages: list[dict] = []
    if existing_raw:
        try:
            messages = json.loads(existing_raw)
            if not isinstance(messages, list):
                messages = []
        except (json.JSONDecodeError, TypeError):
            messages = []

    messages.append({"text": message, "category": category})

    response.set_cookie(
        key=FLASH_COOKIE_NAME,
        value=json.dumps(messages),
        httponly=True,
        samesite="lax",
        max_age=60,
        path="/",
    )


def get_flashes(request: Request) -> list[dict]:
    raw = request.cookies.get(FLASH_COOKIE_NAME)
    if not raw:
        return []
    try:
        messages = json.loads(raw)
        if not isinstance(messages, list):
            return []
        return messages
    except (json.JSONDecodeError, TypeError):
        return []


def clear_flashes(response: Response) -> None:
    response.delete_cookie(
        key=FLASH_COOKIE_NAME,
        path="/",
    )


def get_template_context(
    request: Request,
    current_user: Optional[User] = None,
    **kwargs,
) -> dict:
    flash_messages = get_flashes(request)
    context = {
        "current_user": current_user,
        "flash_messages": flash_messages,
        "current_year": datetime.utcnow().year,
    }
    context.update(kwargs)
    return context


async def log_audit_event(
    db: AsyncSession,
    actor_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: str,
    details: Optional[str] = None,
) -> None:
    from models.audit_log import AuditLog

    try:
        actor_id_str = str(actor_id) if actor_id is not None else None
        audit_entry = AuditLog(
            actor_id=actor_id_str,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
        )
        db.add(audit_entry)
        await db.flush()
    except Exception:
        logger.exception("Failed to write audit log entry")