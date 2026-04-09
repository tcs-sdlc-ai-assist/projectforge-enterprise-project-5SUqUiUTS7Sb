import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dependencies import (
    add_flash,
    clear_flashes,
    get_current_user,
    get_db,
    get_template_context,
    log_audit_event,
    require_role,
)
from models.department import Department
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

VALID_ROLES = ["super_admin", "org_admin", "project_manager", "team_lead", "developer", "viewer"]


@router.get("/users")
async def list_users(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
    search: Optional[str] = None,
    role: Optional[str] = None,
    department_id: Optional[str] = None,
):
    stmt = select(User).options(selectinload(User.department))

    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            (User.username.ilike(search_term)) | (User.email.ilike(search_term))
        )

    if role:
        stmt = stmt.where(User.role == role)

    if department_id:
        try:
            dept_id_int = int(department_id)
            stmt = stmt.where(User.department_id == dept_id_int)
        except (ValueError, TypeError):
            pass

    stmt = stmt.order_by(User.created_at.desc())

    result = await db.execute(stmt)
    users = result.scalars().all()

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    filters = {
        "search": search or "",
        "role": role or "",
        "department_id": department_id or "",
    }

    context = get_template_context(
        request,
        current_user=current_user,
        users=users,
        departments=departments,
        filters=filters,
    )

    response = templates.TemplateResponse(request, "users/list.html", context=context)
    clear_flashes(response)
    return response


@router.get("/users/create")
async def create_user_form(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
):
    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    context = get_template_context(
        request,
        current_user=current_user,
        departments=departments,
        roles=VALID_ROLES,
        user_form=None,
        error=None,
    )

    response = templates.TemplateResponse(request, "users/create.html", context=context)
    clear_flashes(response)
    return response


@router.post("/users/create")
async def create_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(""),
    full_name: str = Form(""),
    role: str = Form("developer"),
    department_id: str = Form(""),
):
    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    errors = []

    username = username.strip()
    email = email.strip() if email else ""
    full_name = full_name.strip() if full_name else ""

    if len(username) < 3:
        errors.append("Username must be at least 3 characters long.")
    if len(username) > 32:
        errors.append("Username must be at most 32 characters long.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if role not in VALID_ROLES:
        errors.append(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")

    if not errors:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            errors.append("Username already exists.")

    if not errors and email:
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none() is not None:
            errors.append("Email already exists.")

    if errors:
        context = get_template_context(
            request,
            current_user=current_user,
            departments=departments,
            roles=VALID_ROLES,
            user_form={
                "username": username,
                "email": email,
                "full_name": full_name,
                "role": role,
                "department_id": department_id,
            },
            errors=errors,
            error=None,
        )
        return templates.TemplateResponse(request, "users/create.html", context=context)

    dept_id_value = None
    if department_id:
        try:
            dept_id_value = int(department_id)
        except (ValueError, TypeError):
            pass

    new_user = User(
        username=username,
        email=email if email else None,
        full_name=full_name if full_name else None,
        password_hash=pwd_context.hash(password),
        role=role,
        department_id=dept_id_value,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="user",
        entity_id=str(new_user.id),
        details=f"Created user '{new_user.username}' with role '{new_user.role}'",
    )

    await db.commit()

    logger.info(
        "User '%s' created by '%s' with role '%s'",
        new_user.username,
        current_user.username,
        new_user.role,
    )

    response = RedirectResponse(url="/users", status_code=303)
    add_flash(request, response, f"User '{new_user.username}' created successfully.", "success")
    return response


@router.get("/users/{user_id}/edit")
async def edit_user_form(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
):
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.department))
    )
    user = result.scalar_one_or_none()

    if user is None:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    context = get_template_context(
        request,
        current_user=current_user,
        edit_user=user,
        departments=departments,
        roles=VALID_ROLES,
        error=None,
    )

    response = templates.TemplateResponse(request, "users/edit.html", context=context)
    clear_flashes(response)
    return response


@router.post("/users/{user_id}/edit")
async def edit_user(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
    username: str = Form(""),
    email: str = Form(""),
    full_name: str = Form(""),
    role: str = Form(""),
    department_id: str = Form(""),
):
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.department))
    )
    user = result.scalar_one_or_none()

    if user is None:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    username = username.strip() if username else user.username
    email = email.strip() if email else ""
    full_name = full_name.strip() if full_name else ""
    role = role.strip() if role else user.role

    errors = []

    if len(username) < 3:
        errors.append("Username must be at least 3 characters long.")
    if len(username) > 32:
        errors.append("Username must be at most 32 characters long.")
    if role not in VALID_ROLES:
        errors.append(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")

    if not errors and username != user.username:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            errors.append("Username already exists.")

    if not errors and email and email != (user.email or ""):
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none() is not None:
            errors.append("Email already exists.")

    if errors:
        context = get_template_context(
            request,
            current_user=current_user,
            edit_user=user,
            departments=departments,
            roles=VALID_ROLES,
            errors=errors,
            error=None,
        )
        return templates.TemplateResponse(request, "users/edit.html", context=context)

    dept_id_value = None
    if department_id:
        try:
            dept_id_value = int(department_id)
        except (ValueError, TypeError):
            pass

    changes = []
    if user.username != username:
        changes.append(f"username: '{user.username}' → '{username}'")
        user.username = username
    if user.email != (email if email else None):
        changes.append(f"email: '{user.email}' → '{email if email else None}'")
        user.email = email if email else None
    if user.full_name != (full_name if full_name else None):
        changes.append(f"full_name: '{user.full_name}' → '{full_name if full_name else None}'")
        user.full_name = full_name if full_name else None
    if user.role != role:
        changes.append(f"role: '{user.role}' → '{role}'")
        user.role = role
    if user.department_id != dept_id_value:
        changes.append(f"department_id: {user.department_id} → {dept_id_value}")
        user.department_id = dept_id_value

    if changes:
        await log_audit_event(
            db=db,
            actor_id=current_user.id,
            action="update",
            entity_type="user",
            entity_id=str(user.id),
            details=f"Updated user '{user.username}': {'; '.join(changes)}",
        )

    await db.commit()

    logger.info(
        "User '%s' (id=%d) updated by '%s'",
        user.username,
        user.id,
        current_user.username,
    )

    response = RedirectResponse(url="/users", status_code=303)
    add_flash(request, response, f"User '{user.username}' updated successfully.", "success")
    return response


@router.post("/users/{user_id}/update-role")
async def update_user_role(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
    role: str = Form(...),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    if role not in VALID_ROLES:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "Invalid role.", "error")
        return response

    old_role = user.role
    if old_role != role:
        user.role = role

        await log_audit_event(
            db=db,
            actor_id=current_user.id,
            action="update",
            entity_type="user",
            entity_id=str(user.id),
            details=f"Changed role of '{user.username}' from '{old_role}' to '{role}'",
        )

        await db.commit()

        logger.info(
            "User '%s' role changed from '%s' to '%s' by '%s'",
            user.username,
            old_role,
            role,
            current_user.username,
        )

    response = RedirectResponse(url="/users", status_code=303)
    add_flash(request, response, f"Role for '{user.username}' updated to '{role}'.", "success")
    return response


@router.post("/users/{user_id}/update-department")
async def update_user_department(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
    department_id: str = Form(""),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    dept_id_value = None
    if department_id:
        try:
            dept_id_value = int(department_id)
        except (ValueError, TypeError):
            pass

    old_dept_id = user.department_id
    if old_dept_id != dept_id_value:
        user.department_id = dept_id_value

        await log_audit_event(
            db=db,
            actor_id=current_user.id,
            action="update",
            entity_type="user",
            entity_id=str(user.id),
            details=f"Changed department of '{user.username}' from {old_dept_id} to {dept_id_value}",
        )

        await db.commit()

        logger.info(
            "User '%s' department changed from %s to %s by '%s'",
            user.username,
            old_dept_id,
            dept_id_value,
            current_user.username,
        )

    response = RedirectResponse(url="/users", status_code=303)
    add_flash(request, response, f"Department for '{user.username}' updated.", "success")
    return response


@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "org_admin"]))],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    if user.id == current_user.id:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "You cannot deactivate your own account.", "error")
        return response

    old_status = user.is_active
    user.is_active = not user.is_active
    new_status = user.is_active

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="user",
        entity_id=str(user.id),
        details=f"Toggled user '{user.username}' active status from {old_status} to {new_status}",
    )

    await db.commit()

    status_text = "activated" if new_status else "deactivated"
    logger.info(
        "User '%s' %s by '%s'",
        user.username,
        status_text,
        current_user.username,
    )

    response = RedirectResponse(url="/users", status_code=303)
    add_flash(request, response, f"User '{user.username}' has been {status_text}.", "success")
    return response


@router.post("/users/{user_id}/delete")
async def delete_user(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    if user.id == current_user.id:
        response = RedirectResponse(url="/users", status_code=303)
        add_flash(request, response, "You cannot delete your own account.", "error")
        return response

    username = user.username

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="user",
        entity_id=str(user.id),
        details=f"Deleted user '{username}' (role: {user.role})",
    )

    await db.delete(user)
    await db.commit()

    logger.info(
        "User '%s' (id=%d) deleted by '%s'",
        username,
        user_id,
        current_user.username,
    )

    response = RedirectResponse(url="/users", status_code=303)
    add_flash(request, response, f"User '{username}' has been deleted.", "success")
    return response