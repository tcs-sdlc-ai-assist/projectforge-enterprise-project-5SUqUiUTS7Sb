import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from datetime import date, datetime
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
from models.label import Label
from models.project import Project, ProjectMember
from models.sprint import Sprint
from models.ticket import Ticket, ticket_labels
from models.time_entry import TimeEntry
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

TICKETS_PER_PAGE = 20


async def _get_project_by_id(db: AsyncSession, project_id: int) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.department),
            selectinload(Project.owner),
            selectinload(Project.members).selectinload(ProjectMember.user),
            selectinload(Project.sprints),
            selectinload(Project.labels),
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_ticket_by_id(db: AsyncSession, ticket_id: int) -> Ticket:
    result = await db.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.project),
            selectinload(Ticket.sprint),
            selectinload(Ticket.assignee),
            selectinload(Ticket.reporter),
            selectinload(Ticket.parent),
            selectinload(Ticket.subtasks),
            selectinload(Ticket.labels),
            selectinload(Ticket.comments).selectinload(Comment.user),
            selectinload(Ticket.time_entries).selectinload(TimeEntry.user),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _generate_ticket_key(project_key: str, ticket_number: int) -> str:
    return f"{project_key}-{ticket_number}"


async def _get_next_ticket_number(db: AsyncSession, project_id: int) -> int:
    result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.project_id == project_id)
    )
    count = result.scalar() or 0
    return count + 1


async def _get_project_members_as_users(db: AsyncSession, project_id: int) -> list:
    result = await db.execute(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
    )
    return list(result.scalars().all())


@router.get("/projects/{project_id}/tickets")
async def list_tickets(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    search: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    ticket_type: Optional[str] = None,
    assignee_id: Optional[str] = None,
    sprint_id: Optional[str] = None,
    label_id: Optional[str] = None,
    sort_by: Optional[str] = None,
    page: int = 1,
):
    project = await _get_project_by_id(db, project_id)

    query = select(Ticket).where(Ticket.project_id == project_id).options(
        selectinload(Ticket.assignee),
        selectinload(Ticket.reporter),
        selectinload(Ticket.sprint),
        selectinload(Ticket.labels),
        selectinload(Ticket.project),
    )

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Ticket.title.ilike(search_filter)) | (Ticket.ticket_key.ilike(search_filter))
        )

    if status:
        query = query.where(Ticket.status == status)

    if priority:
        query = query.where(Ticket.priority == priority)

    if ticket_type:
        query = query.where(Ticket.ticket_type == ticket_type)

    if assignee_id:
        try:
            query = query.where(Ticket.assignee_id == int(assignee_id))
        except (ValueError, TypeError):
            pass

    if sprint_id:
        try:
            query = query.where(Ticket.sprint_id == int(sprint_id))
        except (ValueError, TypeError):
            pass

    if label_id:
        try:
            query = query.join(ticket_labels).where(ticket_labels.c.label_id == int(label_id))
        except (ValueError, TypeError):
            pass

    if sort_by == "created_at_asc":
        query = query.order_by(Ticket.created_at.asc())
    elif sort_by == "priority_desc":
        query = query.order_by(Ticket.priority.desc())
    elif sort_by == "priority_asc":
        query = query.order_by(Ticket.priority.asc())
    elif sort_by == "status_asc":
        query = query.order_by(Ticket.status.asc())
    elif sort_by == "status_desc":
        query = query.order_by(Ticket.status.desc())
    else:
        query = query.order_by(Ticket.created_at.desc())

    count_query = select(func.count()).select_from(
        query.with_only_columns(Ticket.id).subquery()
    )
    total_result = await db.execute(count_query)
    total_tickets = total_result.scalar() or 0
    total_pages = max(1, (total_tickets + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * TICKETS_PER_PAGE
    query = query.offset(offset).limit(TICKETS_PER_PAGE)

    result = await db.execute(query)
    tickets = list(result.scalars().unique().all())

    members = await _get_project_members_as_users(db, project_id)

    sprints_result = await db.execute(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.created_at.desc())
    )
    sprints = list(sprints_result.scalars().all())

    labels_result = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.name)
    )
    labels = list(labels_result.scalars().all())

    filters = {
        "search": search or "",
        "status": status or "",
        "priority": priority or "",
        "ticket_type": ticket_type or "",
        "assignee_id": assignee_id or "",
        "sprint_id": sprint_id or "",
        "label_id": label_id or "",
        "sort_by": sort_by or "created_at_desc",
    }

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        tickets=tickets,
        total_tickets=total_tickets,
        total_pages=total_pages,
        current_page=page,
        filters=filters,
        assignees=members,
        sprints=sprints,
        labels=labels,
    )

    response = templates.TemplateResponse(request, "tickets/list.html", context=context)
    clear_flashes(response)
    return response


@router.get("/projects/{project_id}/tickets/create")
async def create_ticket_form(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager", "team_lead", "developer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)

    members = await _get_project_members_as_users(db, project_id)

    sprints_result = await db.execute(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.created_at.desc())
    )
    sprints = list(sprints_result.scalars().all())

    labels_result = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.name)
    )
    labels = list(labels_result.scalars().all())

    parent_tickets_result = await db.execute(
        select(Ticket).where(Ticket.project_id == project_id).order_by(Ticket.title)
    )
    parent_tickets = list(parent_tickets_result.scalars().all())

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        ticket=None,
        members=members,
        sprints=sprints,
        labels=labels,
        parent_tickets=parent_tickets,
        ticket_label_ids=[],
    )

    response = templates.TemplateResponse(request, "tickets/form.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/{project_id}/tickets/create")
async def create_ticket(
    request: Request,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    title: str = Form(...),
    ticket_type: str = Form(...),
    priority: str = Form(...),
    description: str = Form(""),
    assignee_id: str = Form(""),
    sprint_id: str = Form(""),
    parent_id: str = Form(""),
    story_points: str = Form(""),
    label_ids: list[str] = Form(default=[]),
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager", "team_lead", "developer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)

    ticket_number = await _get_next_ticket_number(db, project_id)
    ticket_key = _generate_ticket_key(project.key, ticket_number)

    assignee_id_val = None
    if assignee_id and assignee_id.strip():
        try:
            assignee_id_val = int(assignee_id)
        except (ValueError, TypeError):
            assignee_id_val = None

    sprint_id_val = None
    if sprint_id and sprint_id.strip():
        try:
            sprint_id_val = int(sprint_id)
        except (ValueError, TypeError):
            sprint_id_val = None

    parent_id_val = None
    if parent_id and parent_id.strip():
        try:
            parent_id_val = int(parent_id)
        except (ValueError, TypeError):
            parent_id_val = None

    story_points_val = None
    if story_points and story_points.strip():
        try:
            story_points_val = int(story_points)
        except (ValueError, TypeError):
            story_points_val = None

    new_ticket = Ticket(
        project_id=project_id,
        ticket_key=ticket_key,
        title=title.strip(),
        description=description.strip() if description else None,
        ticket_type=ticket_type,
        priority=priority,
        status="backlog",
        assignee_id=assignee_id_val,
        reporter_id=current_user.id,
        sprint_id=sprint_id_val,
        parent_id=parent_id_val,
        story_points=story_points_val,
    )

    db.add(new_ticket)
    await db.flush()

    if label_ids:
        for lid_str in label_ids:
            try:
                lid = int(lid_str)
                label_result = await db.execute(
                    select(Label).where(Label.id == lid, Label.project_id == project_id)
                )
                label = label_result.scalar_one_or_none()
                if label:
                    new_ticket.labels.append(label)
            except (ValueError, TypeError):
                continue

    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="ticket",
        entity_id=str(new_ticket.id),
        details=f"Created ticket {ticket_key}: {title}",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{new_ticket.id}",
        status_code=303,
    )
    add_flash(request, response, f"Ticket {ticket_key} created successfully.", "success")
    return response


@router.get("/projects/{project_id}/tickets/{ticket_id}")
async def ticket_detail(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_by_id(db, project_id)
    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    subtasks_result = await db.execute(
        select(Ticket)
        .where(Ticket.parent_id == ticket_id)
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.labels),
        )
        .order_by(Ticket.created_at.asc())
    )
    subtasks = list(subtasks_result.scalars().all())

    comments = sorted(ticket.comments, key=lambda c: c.created_at if c.created_at else datetime.min)

    time_entries = sorted(
        ticket.time_entries,
        key=lambda t: t.spent_date if t.spent_date else date.min,
        reverse=True,
    )

    total_hours = sum(te.hours for te in time_entries if te.hours)

    labels = list(ticket.labels) if ticket.labels else []

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        ticket=ticket,
        subtasks=subtasks,
        comments=comments,
        time_entries=time_entries,
        total_hours=round(total_hours, 2),
        labels=labels,
    )

    response = templates.TemplateResponse(request, "tickets/detail.html", context=context)
    clear_flashes(response)
    return response


@router.get("/projects/{project_id}/tickets/{ticket_id}/edit")
async def edit_ticket_form(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager", "team_lead", "developer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    members = await _get_project_members_as_users(db, project_id)

    sprints_result = await db.execute(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.created_at.desc())
    )
    sprints = list(sprints_result.scalars().all())

    labels_result = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.name)
    )
    labels = list(labels_result.scalars().all())

    parent_tickets_result = await db.execute(
        select(Ticket)
        .where(Ticket.project_id == project_id, Ticket.id != ticket_id)
        .order_by(Ticket.title)
    )
    parent_tickets = list(parent_tickets_result.scalars().all())

    ticket_label_ids = [label.id for label in ticket.labels] if ticket.labels else []

    context = get_template_context(
        request,
        current_user=current_user,
        project=project,
        ticket=ticket,
        members=members,
        sprints=sprints,
        labels=labels,
        parent_tickets=parent_tickets,
        ticket_label_ids=ticket_label_ids,
    )

    response = templates.TemplateResponse(request, "tickets/form.html", context=context)
    clear_flashes(response)
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/edit")
async def update_ticket(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    title: str = Form(...),
    ticket_type: str = Form(...),
    priority: str = Form(...),
    description: str = Form(""),
    status: str = Form(""),
    assignee_id: str = Form(""),
    sprint_id: str = Form(""),
    parent_id: str = Form(""),
    story_points: str = Form(""),
    label_ids: list[str] = Form(default=[]),
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager", "team_lead", "developer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await _get_project_by_id(db, project_id)
    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    ticket.title = title.strip()
    ticket.description = description.strip() if description else None
    ticket.ticket_type = ticket_type
    ticket.priority = priority

    if status and status.strip():
        ticket.status = status

    if assignee_id and assignee_id.strip():
        try:
            ticket.assignee_id = int(assignee_id)
        except (ValueError, TypeError):
            ticket.assignee_id = None
    else:
        ticket.assignee_id = None

    if sprint_id and sprint_id.strip():
        try:
            ticket.sprint_id = int(sprint_id)
        except (ValueError, TypeError):
            ticket.sprint_id = None
    else:
        ticket.sprint_id = None

    if parent_id and parent_id.strip():
        try:
            ticket.parent_id = int(parent_id)
        except (ValueError, TypeError):
            ticket.parent_id = None
    else:
        ticket.parent_id = None

    if story_points and story_points.strip():
        try:
            ticket.story_points = int(story_points)
        except (ValueError, TypeError):
            ticket.story_points = None
    else:
        ticket.story_points = None

    ticket.labels.clear()
    if label_ids:
        for lid_str in label_ids:
            try:
                lid = int(lid_str)
                label_result = await db.execute(
                    select(Label).where(Label.id == lid, Label.project_id == project_id)
                )
                label = label_result.scalar_one_or_none()
                if label:
                    ticket.labels.append(label)
            except (ValueError, TypeError):
                continue

    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="ticket",
        entity_id=str(ticket.id),
        details=f"Updated ticket {ticket.ticket_key}: {title}",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    add_flash(request, response, f"Ticket {ticket.ticket_key} updated successfully.", "success")
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/status")
async def change_ticket_status(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    status: str = Form(...),
):
    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    valid_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed",
                      "open", "resolved", "reopened"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    old_status = ticket.status
    ticket.status = status

    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="ticket",
        entity_id=str(ticket.id),
        details=f"Changed status of {ticket.ticket_key} from {old_status} to {status}",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    add_flash(request, response, f"Ticket status changed to {status.replace('_', ' ').title()}.", "success")
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/delete")
async def delete_ticket(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.role not in ["super_admin", "org_admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    ticket_key = ticket.ticket_key

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="ticket",
        entity_id=str(ticket.id),
        details=f"Deleted ticket {ticket_key}: {ticket.title}",
    )

    await db.delete(ticket)
    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets",
        status_code=303,
    )
    add_flash(request, response, f"Ticket {ticket_key} deleted successfully.", "success")
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/comments")
async def add_comment(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    content: str = Form(...),
    is_internal: str = Form(""),
):
    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    if not content.strip():
        response = RedirectResponse(
            url=f"/projects/{project_id}/tickets/{ticket_id}",
            status_code=303,
        )
        add_flash(request, response, "Comment content cannot be empty.", "error")
        return response

    is_internal_bool = is_internal.lower() in ("true", "on", "1", "yes") if is_internal else False

    comment = Comment(
        ticket_id=ticket_id,
        author_id=current_user.id,
        content=content.strip(),
        is_internal=is_internal_bool,
    )

    db.add(comment)
    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="comment",
        entity_id=str(comment.id),
        details=f"Added comment on ticket {ticket.ticket_key}",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    add_flash(request, response, "Comment added successfully.", "success")
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/comments/{comment_id}/delete")
async def delete_comment(
    request: Request,
    project_id: int,
    ticket_id: int,
    comment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Comment)
        .where(Comment.id == comment_id, Comment.ticket_id == ticket_id)
        .options(selectinload(Comment.user))
    )
    comment = result.scalar_one_or_none()

    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.author_id != current_user.id and current_user.role not in [
        "super_admin", "org_admin", "project_manager"
    ]:
        raise HTTPException(status_code=403, detail="You can only delete your own comments")

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="comment",
        entity_id=str(comment.id),
        details=f"Deleted comment on ticket {ticket_id}",
    )

    await db.delete(comment)
    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    add_flash(request, response, "Comment deleted successfully.", "success")
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/time-entries")
async def add_time_entry(
    request: Request,
    project_id: int,
    ticket_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    hours: str = Form(...),
    spent_date: str = Form(...),
    description: str = Form(""),
):
    ticket = await _get_ticket_by_id(db, ticket_id)

    if ticket.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ticket not found in this project")

    try:
        hours_val = float(hours)
        if hours_val <= 0:
            raise ValueError("Hours must be positive")
    except (ValueError, TypeError):
        response = RedirectResponse(
            url=f"/projects/{project_id}/tickets/{ticket_id}",
            status_code=303,
        )
        add_flash(request, response, "Invalid hours value. Must be a positive number.", "error")
        return response

    try:
        spent_date_val = date.fromisoformat(spent_date)
    except (ValueError, TypeError):
        response = RedirectResponse(
            url=f"/projects/{project_id}/tickets/{ticket_id}",
            status_code=303,
        )
        add_flash(request, response, "Invalid date format.", "error")
        return response

    time_entry = TimeEntry(
        ticket_id=ticket_id,
        user_id=current_user.id,
        hours=hours_val,
        description=description.strip() if description else None,
        spent_date=spent_date_val,
    )

    db.add(time_entry)
    await db.flush()

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="time_entry",
        entity_id=str(time_entry.id),
        details=f"Logged {hours_val}h on ticket {ticket.ticket_key}",
    )

    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    add_flash(request, response, f"Logged {hours_val} hours successfully.", "success")
    return response


@router.post("/projects/{project_id}/tickets/{ticket_id}/time-entries/{entry_id}/delete")
async def delete_time_entry(
    request: Request,
    project_id: int,
    ticket_id: int,
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(TimeEntry)
        .where(TimeEntry.id == entry_id, TimeEntry.ticket_id == ticket_id)
        .options(selectinload(TimeEntry.user))
    )
    time_entry = result.scalar_one_or_none()

    if time_entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")

    if time_entry.user_id != current_user.id and current_user.role not in [
        "super_admin", "org_admin", "project_manager"
    ]:
        raise HTTPException(status_code=403, detail="You can only delete your own time entries")

    await log_audit_event(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="time_entry",
        entity_id=str(time_entry.id),
        details=f"Deleted time entry ({time_entry.hours}h) on ticket {ticket_id}",
    )

    await db.delete(time_entry)
    await db.commit()

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    add_flash(request, response, "Time entry deleted successfully.", "success")
    return response