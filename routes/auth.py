import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import (
    add_flash,
    clear_flashes,
    destroy_session,
    get_db,
    get_optional_user,
    get_template_context,
    log_audit_event,
    set_session_cookie,
)
from models.user import User

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/login")
async def login_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Optional[User], Depends(get_optional_user)],
):
    if current_user is not None:
        return RedirectResponse(url="/dashboard", status_code=302)

    context = get_template_context(request, current_user=current_user)
    resp = templates.TemplateResponse(request, "auth/login.html", context=context)
    clear_flashes(resp)
    return resp


@router.post("/login")
async def login_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not pwd_context.verify(password, user.password_hash):
        context = get_template_context(
            request,
            current_user=None,
            error="Invalid username or password.",
            username=username,
        )
        return templates.TemplateResponse(
            request, "auth/login.html", context=context, status_code=400
        )

    if not user.is_active:
        context = get_template_context(
            request,
            current_user=None,
            error="Your account has been deactivated. Please contact an administrator.",
            username=username,
        )
        return templates.TemplateResponse(
            request, "auth/login.html", context=context, status_code=400
        )

    response = RedirectResponse(url="/dashboard", status_code=302)
    set_session_cookie(response, user.id)
    add_flash(request, response, "Welcome back, " + user.username + "!", "success")

    logger.info("User '%s' logged in successfully", user.username)

    return response


@router.get("/register")
async def register_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Optional[User], Depends(get_optional_user)],
):
    if current_user is not None:
        return RedirectResponse(url="/dashboard", status_code=302)

    context = get_template_context(request, current_user=current_user)
    resp = templates.TemplateResponse(request, "auth/register.html", context=context)
    clear_flashes(resp)
    return resp


@router.post("/register")
async def register_submit(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    errors: list[str] = []

    username = username.strip()

    if len(username) < 3:
        errors.append("Username must be at least 3 characters long.")
    if len(username) > 32:
        errors.append("Username must be at most 32 characters long.")
    if not username.isalnum():
        errors.append("Username must contain only letters and numbers.")

    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")

    if password != confirm_password:
        errors.append("Passwords do not match.")

    if not errors:
        result = await db.execute(select(User).where(User.username == username))
        existing_user = result.scalar_one_or_none()
        if existing_user is not None:
            errors.append("Username is already taken. Please choose another.")

    if errors:
        context = get_template_context(
            request,
            current_user=None,
            errors=errors,
            username=username,
        )
        return templates.TemplateResponse(
            request, "auth/register.html", context=context, status_code=400
        )

    password_hash = pwd_context.hash(password)

    new_user = User(
        username=username,
        email=f"{username}@projectforge.local",
        full_name=None,
        password_hash=password_hash,
        role="developer",
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    await log_audit_event(
        db=db,
        actor_id=new_user.id,
        action="create",
        entity_type="user",
        entity_id=str(new_user.id),
        details=f"User '{new_user.username}' registered",
    )
    await db.commit()

    response = RedirectResponse(url="/dashboard", status_code=302)
    set_session_cookie(response, new_user.id)
    add_flash(
        request,
        response,
        "Account created successfully! Welcome to ProjectForge.",
        "success",
    )

    logger.info("New user '%s' registered (id=%s)", new_user.username, new_user.id)

    return response


@router.post("/logout")
async def logout(
    request: Request,
):
    response = RedirectResponse(url="/", status_code=302)
    destroy_session(response)

    logger.info("User logged out")

    return response