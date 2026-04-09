import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
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
from models.comment import Comment
from models.department import Department
from models.label import Label
from models.project import Project, ProjectMember
from models.sprint import Sprint
from models.ticket import Ticket
from models.time_entry import TimeEntry
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def generate_project_key(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip()
    words = cleaned.split()
    if len(words) >= 2:
        key = "".join(w[0] for w in words[:4]).upper()
    else:
        key = cleaned[:4].upper()
    if not key:
        key = "PROJ"
    return key[:12]


async def get_project_by_id_or_404(
    project_id: int,
    db: AsyncSession,
) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.owner),
            selectinload(Project.department),
            selectinload(Project.members).selectinload(ProjectMember.user),
            selectinload(Project.sprints),
            selectinload(Project.tickets).selectinload(Ticket.assignee),
            selectinload(Project.labels),
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/projects")
async def list_projects(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    search: Optional[str] = None,
    status: Optional[str] = None,
    department: Optional[str] = None,
    page: int = 1,
):
    page_size = 20
    if page < 1:
        page = 1

    query = select(Project).options(
        selectinload(Project.owner),
        selectinload(Project.department),
        selectinload(Project.members),
    )

    if search:
        search_term = f"%{search}%"
        query = query.where(
            (Project.name.ilike(search_term)) | (Project.key.ilike(search_term))
        )

    if status:
        query = query.where(Project.status == status)

    if department:
        try:
            dept_id = int(department)
            query = query.where(Project.department_id == dept_id)
        except (ValueError, TypeError):
            pass

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * page_size
    query = query.order_by(Project.updated_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    projects = result.scalars().unique().all()

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    filters = {
        "search": search or "",
        "status": status or "",
        "department": department or "",
    }

    context = get_template_context(
        request,
        current_user=current_user,
        projects=projects,
        departments=departments,
        filters=filters,
        total_count=total_count,
        total_pages=total_pages,
        current_page=page,
        page_size=page_size,
        status_options=["planning", "active", "on_hold", "completed", "archived"],
    )

    response = templates.TemplateResponse(request, "projects/list.html", context=context)
    clear_flashes(response)
    return response


@router.get("/projects/create")
async def create_project_form(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    context = get_template_context(
        request,
        current_user=current_user,
        project=None,
        departments=departments,
    )

    response = templates.TemplateResponse(request, "projects/form.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/create")
async def create_project(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("planning"),
    department_id: str = Form(""),
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    name = name.strip()
    if not name:
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()
        context = get_template_context(
            request,
            current_user=current_user,
            project=None,
            departments=departments,
            error="Project name is required.",
        )
        return templates.TemplateResponse(request, "projects/form.html", context=context, status_code=400)

    existing = await db.execute(select(Project).where(Project.name == name))
    if existing.scalar_one_or_none():
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()
        context = get_template_context(
            request,
            current_user=current_user,
            project=None,
            departments=departments,
            error="A project with this name already exists.",
        )
        return templates.TemplateResponse(request, "projects/form.html", context=context, status_code=400)

    base_key = generate_project_key(name)
    key = base_key
    suffix = 1
    while True:
        key_check = await db.execute(select(Project).where(Project.key == key))
        if key_check.scalar_one_or_none() is None:
            break
        key = f"{base_key}{suffix}"[:12]
        suffix += 1

    valid_statuses = ["planning", "active", "on_hold", "completed", "archived"]
    if status not in valid_statuses:
        status = "planning"

    dept_id = None
    if department_id:
        try:
            dept_id = int(department_id)
        except (ValueError, TypeError):
            dept_id = None

    project = Project(
        key=key,
        name=name,
        description=description.strip() if description else None,
        status=status,
        department_id=dept_id,
        owner_id=current_user.id,
    )
    db.add(project)
    await db.flush()

    member = ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        role="project_manager",
    )
    db.add(member)

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="project",
        entity_id=str(project.id),
        details=f"Created project '{project.name}' with key '{project.key}'",
    )

    await db.commit()

    response = RedirectResponse(url=f"/projects/{project.id}", status_code=303)
    add_flash(request, response, f"Project '{project.name}' created successfully.", "success")
    return response


@router.get("/projects/{project_id}")
async def project_detail(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_by_id_or_404(project_id, db)

    members = project.members or []
    sprints = sorted(
        (project.sprints or []),
        key=lambda s: s.created_at if s.created_at else s.id,
        reverse=True,
    )[:10]
    tickets = sorted(
        (project.tickets or []),
        key=lambda t: t.created_at if t.created_at else t.id,
        reverse=True,
    )[:10]

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        members=members,
        sprints=sprints,
        tickets=tickets,
    )

    response = templates.TemplateResponse(request, "projects/detail.html", context=context)
    clear_flashes(response)
    return response


@router.get("/projects/{project_id}/edit")
async def edit_project_form(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_project_by_id_or_404(project_id, db)

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        departments=departments,
    )

    response = templates.TemplateResponse(request, "projects/form.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/{project_id}/edit")
async def update_project(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("planning"),
    department_id: str = Form(""),
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_project_by_id_or_404(project_id, db)

    name = name.strip()
    if not name:
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            departments=departments,
            error="Project name is required.",
        )
        return templates.TemplateResponse(request, "projects/form.html", context=context, status_code=400)

    existing = await db.execute(
        select(Project).where(Project.name == name, Project.id != project_id)
    )
    if existing.scalar_one_or_none():
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()
        context = get_template_context(
            request,
            current_user=current_user,
            project=project,
            departments=departments,
            error="A project with this name already exists.",
        )
        return templates.TemplateResponse(request, "projects/form.html", context=context, status_code=400)

    valid_statuses = ["planning", "active", "on_hold", "completed", "archived"]
    if status not in valid_statuses:
        status = project.status

    dept_id = None
    if department_id:
        try:
            dept_id = int(department_id)
        except (ValueError, TypeError):
            dept_id = None

    project.name = name
    project.description = description.strip() if description else None
    project.status = status
    project.department_id = dept_id

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="project",
        entity_id=str(project.id),
        details=f"Updated project '{project.name}'",
    )

    await db.commit()

    response = RedirectResponse(url=f"/projects/{project.id}", status_code=303)
    add_flash(request, response, f"Project '{project.name}' updated successfully.", "success")
    return response


@router.post("/projects/{project_id}/delete")
async def delete_project(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_project_by_id_or_404(project_id, db)
    project_name = project.name

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="project",
        entity_id=str(project.id),
        details=f"Deleted project '{project_name}'",
    )

    await db.delete(project)
    await db.commit()

    response = RedirectResponse(url="/projects", status_code=303)
    add_flash(request, response, f"Project '{project_name}' deleted successfully.", "success")
    return response


@router.get("/projects/{project_id}/members")
async def project_members(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_by_id_or_404(project_id, db)

    member_user_ids = [m.user_id for m in (project.members or [])]
    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.username)
    )
    all_users = users_result.scalars().all()
    available_users = [u for u in all_users if u.id not in member_user_ids]

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        members=project.members or [],
        available_users=available_users,
    )

    response = templates.TemplateResponse(request, "projects/members.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/{project_id}/members/add")
async def add_project_member(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    user_id: str = Form(...),
    role: str = Form("developer"),
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_project_by_id_or_404(project_id, db)

    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        response = RedirectResponse(url=f"/projects/{project_id}/members", status_code=303)
        add_flash(request, response, "Invalid user selected.", "error")
        return response

    user_result = await db.execute(select(User).where(User.id == uid))
    user = user_result.scalar_one_or_none()
    if user is None:
        response = RedirectResponse(url=f"/projects/{project_id}/members", status_code=303)
        add_flash(request, response, "User not found.", "error")
        return response

    existing_member = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == uid,
        )
    )
    if existing_member.scalar_one_or_none():
        response = RedirectResponse(url=f"/projects/{project_id}/members", status_code=303)
        add_flash(request, response, "User is already a member of this project.", "warning")
        return response

    valid_roles = ["project_manager", "team_lead", "developer", "viewer"]
    if role not in valid_roles:
        role = "developer"

    member = ProjectMember(
        project_id=project_id,
        user_id=uid,
        role=role,
    )
    db.add(member)

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="project_member",
        entity_id=str(project_id),
        details=f"Added user '{user.username}' to project '{project.name}' as {role}",
    )

    await db.commit()

    response = RedirectResponse(url=f"/projects/{project_id}/members", status_code=303)
    add_flash(request, response, f"User '{user.username}' added to project.", "success")
    return response


@router.post("/projects/{project_id}/members/{member_id}/remove")
async def remove_project_member(
    request: Request,
    project_id: int,
    member_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    member_result = await db.execute(
        select(ProjectMember)
        .where(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
        .options(selectinload(ProjectMember.user), selectinload(ProjectMember.project))
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    member_username = member.user.username if member.user else "Unknown"
    project_name = member.project.name if member.project else "Unknown"

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="project_member",
        entity_id=str(project_id),
        details=f"Removed user '{member_username}' from project '{project_name}'",
    )

    await db.delete(member)
    await db.commit()

    response = RedirectResponse(url=f"/projects/{project_id}/members", status_code=303)
    add_flash(request, response, f"User '{member_username}' removed from project.", "success")
    return response


@router.get("/projects/{project_id}/board")
async def kanban_board(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    assignee_id: Optional[str] = None,
    label_id: Optional[str] = None,
    sprint_id: Optional[str] = None,
):
    project = await get_project_by_id_or_404(project_id, db)

    ticket_query = (
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.labels),
            selectinload(Ticket.sprint),
        )
    )

    if assignee_id:
        try:
            aid = int(assignee_id)
            ticket_query = ticket_query.where(Ticket.assignee_id == aid)
        except (ValueError, TypeError):
            pass

    if sprint_id:
        try:
            sid = int(sprint_id)
            ticket_query = ticket_query.where(Ticket.sprint_id == sid)
        except (ValueError, TypeError):
            pass

    ticket_result = await db.execute(ticket_query)
    all_tickets = ticket_result.scalars().unique().all()

    if label_id:
        try:
            lid = int(label_id)
            all_tickets = [
                t for t in all_tickets
                if any(lbl.id == lid for lbl in (t.labels or []))
            ]
        except (ValueError, TypeError):
            pass

    status_keys = ["backlog", "todo", "in_progress", "in_review", "done", "closed"]
    columns = {s: [] for s in status_keys}
    for ticket in all_tickets:
        ticket_status = ticket.status or "backlog"
        if ticket_status in columns:
            columns[ticket_status].append(ticket)
        else:
            columns["backlog"].append(ticket)

    member_user_ids = [m.user_id for m in (project.members or [])]
    if member_user_ids:
        members_result = await db.execute(
            select(User).where(User.id.in_(member_user_ids)).order_by(User.username)
        )
        members = members_result.scalars().all()
    else:
        members = []

    labels = project.labels or []
    sprints = project.sprints or []

    filters = {
        "assignee_id": assignee_id or "",
        "label_id": label_id or "",
        "sprint_id": sprint_id or "",
    }

    total_tickets = len(all_tickets)

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        columns=columns,
        members=members,
        labels=labels,
        sprints=sprints,
        filters=filters,
        total_tickets=total_tickets,
    )

    response = templates.TemplateResponse(request, "projects/board.html", context=context)
    clear_flashes(response)
    return response


@router.patch("/api/projects/{project_id}/tickets/{ticket_id}/status")
async def api_update_ticket_status(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    body = await request.json()
    new_status = body.get("status")

    valid_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.project_id == project_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    old_status = ticket.status
    ticket.status = new_status

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="ticket",
        entity_id=str(ticket.id),
        details=f"Changed ticket status from '{old_status}' to '{new_status}'",
    )

    await db.commit()

    return {"ok": True, "ticket_id": ticket_id, "status": new_status}