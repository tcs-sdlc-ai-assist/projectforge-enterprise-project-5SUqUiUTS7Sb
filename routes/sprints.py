import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dependencies import (
    add_flash,
    clear_flashes,
    get_current_user,
    get_db,
    get_template_context,
    log_audit_event,
)
from models.project import Project
from models.sprint import Sprint
from models.ticket import Ticket
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

MANAGER_ROLES = ["super_admin", "org_admin", "project_manager", "team_lead"]


async def _get_project_by_id(db: AsyncSession, project_id: int) -> Optional[Project]:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.department),
            selectinload(Project.owner),
            selectinload(Project.members),
            selectinload(Project.sprints),
        )
    )
    return result.scalar_one_or_none()


async def _get_sprint_with_tickets(db: AsyncSession, sprint_id: int) -> Optional[Sprint]:
    result = await db.execute(
        select(Sprint)
        .where(Sprint.id == sprint_id)
        .options(
            selectinload(Sprint.project),
            selectinload(Sprint.tickets),
        )
    )
    return result.scalar_one_or_none()


@router.get("/projects/{project_id}/sprints")
async def list_sprints(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Sprint)
        .where(Sprint.project_id == project_id)
        .options(
            selectinload(Sprint.project),
            selectinload(Sprint.tickets),
        )
        .order_by(Sprint.created_at.desc())
    )
    sprints = result.scalars().all()

    sprints_with_counts = []
    for sprint in sprints:
        sprint.ticket_count = len(sprint.tickets) if sprint.tickets else 0
        sprints_with_counts.append(sprint)

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        sprints=sprints_with_counts,
    )

    response = templates.TemplateResponse(request, "sprints/list.html", context=context)
    clear_flashes(response)
    return response


@router.get("/projects/{project_id}/sprints/create")
async def create_sprint_form(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        sprint=None,
        error=None,
    )

    response = templates.TemplateResponse(request, "sprints/form.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/{project_id}/sprints/create")
async def create_sprint(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    goal: str = Form(""),
    start_date: str = Form(...),
    end_date: str = Form(...),
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError:
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=None,
            error="Invalid date format. Please use YYYY-MM-DD.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    if parsed_end <= parsed_start:
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=None,
            error="End date must be after start date.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    if not name.strip():
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=None,
            error="Sprint name is required.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    new_sprint = Sprint(
        project_id=project_id,
        name=name.strip(),
        goal=goal.strip() if goal else None,
        status="planning",
        start_date=parsed_start,
        end_date=parsed_end,
    )
    db.add(new_sprint)

    try:
        await db.flush()
    except Exception:
        await db.rollback()
        logger.exception("Failed to create sprint")
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=None,
            error="Failed to create sprint. A sprint with this name may already exist.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="sprint",
        entity_id=str(new_sprint.id),
        details=f"Created sprint '{new_sprint.name}' for project '{project.name}'",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    add_flash(request, response, f"Sprint '{new_sprint.name}' created successfully.", "success")
    return response


@router.get("/projects/{project_id}/sprints/{sprint_id}")
async def sprint_detail(
    request: Request,
    project_id: int,
    sprint_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    sprint = await _get_sprint_with_tickets(db, sprint_id)
    if sprint is None or sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found")

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        sprint=sprint,
        tickets=sprint.tickets if sprint.tickets else [],
    )

    response = templates.TemplateResponse(request, "sprints/list.html", context=context)
    clear_flashes(response)
    return response


@router.get("/projects/{project_id}/sprints/{sprint_id}/edit")
async def edit_sprint_form(
    request: Request,
    project_id: int,
    sprint_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    sprint = await _get_sprint_with_tickets(db, sprint_id)
    if sprint is None or sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found")

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        sprint=sprint,
        error=None,
    )

    response = templates.TemplateResponse(request, "sprints/form.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/{project_id}/sprints/{sprint_id}/edit")
async def edit_sprint(
    request: Request,
    project_id: int,
    sprint_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    goal: str = Form(""),
    start_date: str = Form(...),
    end_date: str = Form(...),
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    sprint = await _get_sprint_with_tickets(db, sprint_id)
    if sprint is None or sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found")

    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError:
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=sprint,
            error="Invalid date format. Please use YYYY-MM-DD.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    if parsed_end <= parsed_start:
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=sprint,
            error="End date must be after start date.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    if not name.strip():
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=sprint,
            error="Sprint name is required.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    sprint.name = name.strip()
    sprint.goal = goal.strip() if goal else None
    sprint.start_date = parsed_start
    sprint.end_date = parsed_end

    try:
        await db.flush()
    except Exception:
        await db.rollback()
        logger.exception("Failed to update sprint")
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            sprint=sprint,
            error="Failed to update sprint. A sprint with this name may already exist.",
        )
        return templates.TemplateResponse(request, "sprints/form.html", context=context, status_code=400)

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="sprint",
        entity_id=str(sprint.id),
        details=f"Updated sprint '{sprint.name}' in project '{project.name}'",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    add_flash(request, response, f"Sprint '{sprint.name}' updated successfully.", "success")
    return response


@router.post("/projects/{project_id}/sprints/{sprint_id}/start")
async def start_sprint(
    request: Request,
    project_id: int,
    sprint_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    sprint = await _get_sprint_with_tickets(db, sprint_id)
    if sprint is None or sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found")

    if sprint.status != "planning":
        response = RedirectResponse(
            url=f"/projects/{project_id}/sprints",
            status_code=303,
        )
        add_flash(
            request,
            response,
            f"Sprint '{sprint.name}' cannot be started because it is currently '{sprint.status}'.",
            "error",
        )
        return response

    active_result = await db.execute(
        select(Sprint).where(
            Sprint.project_id == project_id,
            Sprint.status == "active",
        )
    )
    active_sprint = active_result.scalar_one_or_none()

    if active_sprint is not None:
        response = RedirectResponse(
            url=f"/projects/{project_id}/sprints",
            status_code=303,
        )
        add_flash(
            request,
            response,
            f"Cannot start sprint '{sprint.name}'. Sprint '{active_sprint.name}' is already active. Only one active sprint is allowed per project.",
            "error",
        )
        return response

    sprint.status = "active"

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="sprint",
        entity_id=str(sprint.id),
        details=f"Started sprint '{sprint.name}' in project '{project.name}'",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    add_flash(request, response, f"Sprint '{sprint.name}' is now active.", "success")
    return response


@router.post("/projects/{project_id}/sprints/{sprint_id}/complete")
async def complete_sprint(
    request: Request,
    project_id: int,
    sprint_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    sprint = await _get_sprint_with_tickets(db, sprint_id)
    if sprint is None or sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found")

    if sprint.status != "active":
        response = RedirectResponse(
            url=f"/projects/{project_id}/sprints",
            status_code=303,
        )
        add_flash(
            request,
            response,
            f"Sprint '{sprint.name}' cannot be completed because it is currently '{sprint.status}'.",
            "error",
        )
        return response

    sprint.status = "completed"

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="sprint",
        entity_id=str(sprint.id),
        details=f"Completed sprint '{sprint.name}' in project '{project.name}'",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    add_flash(request, response, f"Sprint '{sprint.name}' has been completed.", "success")
    return response