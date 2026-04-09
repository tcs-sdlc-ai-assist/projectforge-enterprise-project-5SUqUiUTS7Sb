import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import async_session_factory
from dependencies import (
    get_current_user,
    get_db,
    get_template_context,
    add_flash,
    clear_flashes,
    log_audit_event,
)
from models.label import Label
from models.project import Project
from models.ticket import ticket_labels
from models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


async def get_project_by_id_or_key(db: AsyncSession, project_id_or_key: str) -> Optional[Project]:
    try:
        pid = int(project_id_or_key)
        result = await db.execute(
            select(Project).where(Project.id == pid)
        )
        project = result.scalar_one_or_none()
        if project:
            return project
    except (ValueError, TypeError):
        pass

    result = await db.execute(
        select(Project).where(Project.key == project_id_or_key)
    )
    return result.scalar_one_or_none()


@router.get("/projects/{project_id}/labels")
async def list_labels(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_by_id_or_key(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Label)
        .where(Label.project_id == project.id)
        .options(selectinload(Label.tickets))
        .order_by(Label.name)
    )
    labels = result.scalars().all()

    labels_with_counts = []
    for label in labels:
        label.ticket_count = len(label.tickets) if label.tickets else 0
        labels_with_counts.append(label)

    response = Response()
    clear_flashes(response)

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        labels=labels_with_counts,
    )

    return templates.TemplateResponse(
        request,
        "labels/list.html",
        context=context,
        headers=dict(response.headers),
    )


@router.post("/projects/{project_id}/labels")
async def create_label(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    color: str = Form("#6b7280"),
):
    project = await get_project_by_id_or_key(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role not in ["super_admin", "org_admin", "project_manager", "team_lead", "developer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to create labels")

    name = name.strip()
    if not name:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels",
            status_code=303,
        )
        add_flash(request, response, "Label name is required.", "error")
        return response

    if len(name) > 32:
        name = name[:32]

    if not color or not color.startswith("#") or len(color) != 7:
        color = "#6b7280"

    result = await db.execute(
        select(Label).where(
            Label.project_id == project.id,
            func.lower(Label.name) == name.lower(),
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels",
            status_code=303,
        )
        add_flash(request, response, f"A label named '{name}' already exists in this project.", "error")
        return response

    label = Label(
        project_id=project.id,
        name=name,
        color=color,
    )
    db.add(label)
    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="label",
        entity_id=str(label.id),
        details=f"Created label '{name}' in project '{project.name}'",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/labels",
        status_code=303,
    )
    add_flash(request, response, f"Label '{name}' created successfully.", "success")
    return response


@router.post("/projects/{project_id}/labels/{label_id}/delete")
async def delete_label(
    request: Request,
    project_id: str,
    label_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_by_id_or_key(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role not in ["super_admin", "org_admin", "project_manager", "team_lead", "developer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete labels")

    result = await db.execute(
        select(Label).where(
            Label.id == label_id,
            Label.project_id == project.id,
        )
    )
    label = result.scalar_one_or_none()

    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    label_name = label.name

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="label",
        entity_id=str(label_id),
        details=f"Deleted label '{label_name}' from project '{project.name}'",
    )

    await db.delete(label)
    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/labels",
        status_code=303,
    )
    add_flash(request, response, f"Label '{label_name}' deleted successfully.", "success")
    return response