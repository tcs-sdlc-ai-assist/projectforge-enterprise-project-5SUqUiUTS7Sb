import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
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


@router.get("/departments")
async def list_departments(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
):
    result = await db.execute(
        select(Department)
        .options(
            selectinload(Department.head),
            selectinload(Department.members),
        )
        .order_by(Department.name)
    )
    departments = result.scalars().all()

    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.username)
    )
    users = users_result.scalars().all()

    context = get_template_context(
        request,
        current_user=current_user,
        departments=departments,
        users=users,
    )

    resp = templates.TemplateResponse(request, "departments/list.html", context=context)
    clear_flashes(resp)
    return resp


@router.post("/departments")
async def create_department(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    head_id: str = Form(""),
):
    code = code.strip().upper()
    name = name.strip()

    if not name:
        add_flash(request, response, "Department name is required.", "error")
        resp = RedirectResponse(url="/departments", status_code=303)
        return resp

    if not code:
        add_flash(request, response, "Department code is required.", "error")
        resp = RedirectResponse(url="/departments", status_code=303)
        return resp

    if len(code) > 10:
        add_flash(request, response, "Department code must be 10 characters or fewer.", "error")
        resp = RedirectResponse(url="/departments", status_code=303)
        return resp

    existing_name = await db.execute(
        select(Department).where(Department.name == name)
    )
    if existing_name.scalar_one_or_none() is not None:
        add_flash(request, response, f"A department with the name '{name}' already exists.", "error")
        resp = RedirectResponse(url="/departments", status_code=303)
        return resp

    existing_code = await db.execute(
        select(Department).where(Department.code == code)
    )
    if existing_code.scalar_one_or_none() is not None:
        add_flash(request, response, f"A department with the code '{code}' already exists.", "error")
        resp = RedirectResponse(url="/departments", status_code=303)
        return resp

    head_id_int: Optional[int] = None
    if head_id and head_id.strip():
        try:
            head_id_int = int(head_id)
        except (ValueError, TypeError):
            head_id_int = None

    department = Department(
        name=name,
        code=code,
        description=description if description.strip() else None,
        head_id=head_id_int,
    )
    db.add(department)
    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="department",
        entity_id=str(department.id),
        details=f"Created department '{name}' with code '{code}'",
    )

    await db.commit()

    logger.info("Department '%s' (code=%s) created by user %s", name, code, current_user.username)

    resp = RedirectResponse(url="/departments", status_code=303)
    add_flash(request, resp, f"Department '{name}' created successfully.", "success")
    return resp


@router.get("/departments/{department_id}/edit")
async def edit_department_form(
    request: Request,
    department_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
):
    result = await db.execute(
        select(Department)
        .where(Department.id == department_id)
        .options(
            selectinload(Department.head),
            selectinload(Department.members),
        )
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        add_flash(request, resp, "Department not found.", "error")
        return resp

    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.username)
    )
    users = users_result.scalars().all()

    context = get_template_context(
        request,
        current_user=current_user,
        department=department,
        users=users,
    )

    resp = templates.TemplateResponse(request, "departments/edit.html", context=context)
    clear_flashes(resp)
    return resp


@router.post("/departments/{department_id}/edit")
async def update_department(
    request: Request,
    response: Response,
    department_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    head_id: str = Form(""),
):
    result = await db.execute(
        select(Department)
        .where(Department.id == department_id)
        .options(
            selectinload(Department.head),
            selectinload(Department.members),
        )
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        add_flash(request, resp, "Department not found.", "error")
        return resp

    name = name.strip()
    code = code.strip().upper()

    if not name:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        add_flash(request, resp, "Department name is required.", "error")
        return resp

    if not code:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        add_flash(request, resp, "Department code is required.", "error")
        return resp

    if len(code) > 10:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        add_flash(request, resp, "Department code must be 10 characters or fewer.", "error")
        return resp

    existing_name = await db.execute(
        select(Department).where(Department.name == name, Department.id != department_id)
    )
    if existing_name.scalar_one_or_none() is not None:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        add_flash(request, resp, f"A department with the name '{name}' already exists.", "error")
        return resp

    existing_code = await db.execute(
        select(Department).where(Department.code == code, Department.id != department_id)
    )
    if existing_code.scalar_one_or_none() is not None:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        add_flash(request, resp, f"A department with the code '{code}' already exists.", "error")
        return resp

    head_id_int: Optional[int] = None
    if head_id and head_id.strip():
        try:
            head_id_int = int(head_id)
        except (ValueError, TypeError):
            head_id_int = None

    changes = []
    if department.name != name:
        changes.append(f"name: '{department.name}' → '{name}'")
        department.name = name
    if department.code != code:
        changes.append(f"code: '{department.code}' → '{code}'")
        department.code = code
    if department.description != (description.strip() if description.strip() else None):
        changes.append("description updated")
        department.description = description.strip() if description.strip() else None
    if department.head_id != head_id_int:
        changes.append(f"head_id: {department.head_id} → {head_id_int}")
        department.head_id = head_id_int

    await db.flush()

    details = f"Updated department '{name}'"
    if changes:
        details += f" — changes: {', '.join(changes)}"

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="department",
        entity_id=str(department.id),
        details=details,
    )

    await db.commit()

    logger.info("Department '%s' (id=%d) updated by user %s", name, department_id, current_user.username)

    resp = RedirectResponse(url="/departments", status_code=303)
    add_flash(request, resp, f"Department '{name}' updated successfully.", "success")
    return resp


@router.post("/departments/{department_id}/delete")
async def delete_department(
    request: Request,
    response: Response,
    department_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
):
    result = await db.execute(
        select(Department)
        .where(Department.id == department_id)
        .options(
            selectinload(Department.members),
        )
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        add_flash(request, resp, "Department not found.", "error")
        return resp

    member_count = len(department.members) if department.members else 0
    if member_count > 0:
        resp = RedirectResponse(url="/departments", status_code=303)
        add_flash(
            request,
            resp,
            f"Cannot delete department '{department.name}' because it has {member_count} assigned user{'s' if member_count != 1 else ''}. "
            f"Reassign or remove all users from this department first.",
            "error",
        )
        return resp

    dept_name = department.name
    dept_code = department.code

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="department",
        entity_id=str(department.id),
        details=f"Deleted department '{dept_name}' (code: {dept_code})",
    )

    await db.delete(department)
    await db.commit()

    logger.info("Department '%s' (id=%d) deleted by user %s", dept_name, department_id, current_user.username)

    resp = RedirectResponse(url="/departments", status_code=303)
    add_flash(request, resp, f"Department '{dept_name}' deleted successfully.", "success")
    return resp