import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dependencies import (
    clear_flashes,
    get_current_user,
    get_db,
    get_template_context,
)
from models.audit_log import AuditLog
from models.project import Project
from models.sprint import Sprint
from models.ticket import Ticket
from models.time_entry import TimeEntry
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/dashboard")
async def dashboard(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    response = Response()

    try:
        total_projects = await _get_total_projects(db, current_user)
        active_tickets = await _get_active_tickets(db, current_user)
        hours_logged_this_week = await _get_hours_logged_this_week(db, current_user)
        overdue_tickets = await _get_overdue_tickets(db, current_user)
        ticket_status_distribution = await _get_ticket_status_distribution(db, current_user)
        project_status_breakdown = await _get_project_status_breakdown(db, current_user)
        recent_activity = await _get_recent_activity(db, limit=10)
        top_contributors = await _get_top_contributors(db, limit=5)
    except Exception:
        logger.exception("Error aggregating dashboard data")
        total_projects = 0
        active_tickets = 0
        hours_logged_this_week = 0.0
        overdue_tickets = 0
        ticket_status_distribution = []
        project_status_breakdown = []
        recent_activity = []
        top_contributors = []

    context = get_template_context(
        request,
        current_user=current_user,
        total_projects=total_projects,
        active_tickets=active_tickets,
        hours_logged_this_week=round(hours_logged_this_week, 1),
        overdue_tickets=overdue_tickets,
        ticket_status_distribution=ticket_status_distribution,
        project_status_breakdown=project_status_breakdown,
        recent_activity=recent_activity,
        top_contributors=top_contributors,
    )

    template_response = templates.TemplateResponse(
        request, "dashboard/index.html", context=context
    )

    clear_flashes(template_response)

    return template_response


async def _get_total_projects(db: AsyncSession, current_user: User) -> int:
    if current_user.role in ("super_admin", "org_admin"):
        result = await db.execute(select(func.count(Project.id)))
    else:
        result = await db.execute(
            select(func.count(Project.id)).where(Project.owner_id == current_user.id)
        )
    count = result.scalar_one_or_none()
    return count if count else 0


async def _get_active_tickets(db: AsyncSession, current_user: User) -> int:
    active_statuses = ("backlog", "todo", "in_progress", "in_review")
    if current_user.role in ("super_admin", "org_admin"):
        result = await db.execute(
            select(func.count(Ticket.id)).where(Ticket.status.in_(active_statuses))
        )
    else:
        result = await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.status.in_(active_statuses),
                (Ticket.assignee_id == current_user.id) | (Ticket.reporter_id == current_user.id),
            )
        )
    count = result.scalar_one_or_none()
    return count if count else 0


async def _get_hours_logged_this_week(db: AsyncSession, current_user: User) -> float:
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    if current_user.role in ("super_admin", "org_admin"):
        result = await db.execute(
            select(func.coalesce(func.sum(TimeEntry.hours), 0.0)).where(
                TimeEntry.spent_date >= start_of_week
            )
        )
    else:
        result = await db.execute(
            select(func.coalesce(func.sum(TimeEntry.hours), 0.0)).where(
                TimeEntry.spent_date >= start_of_week,
                TimeEntry.user_id == current_user.id,
            )
        )
    total = result.scalar_one_or_none()
    return float(total) if total else 0.0


async def _get_overdue_tickets(db: AsyncSession, current_user: User) -> int:
    active_statuses = ("backlog", "todo", "in_progress", "in_review")

    stmt = (
        select(func.count(Ticket.id))
        .join(Sprint, Ticket.sprint_id == Sprint.id, isouter=True)
        .where(
            Ticket.status.in_(active_statuses),
            Sprint.end_date < date.today(),
            Sprint.end_date.isnot(None),
        )
    )

    if current_user.role not in ("super_admin", "org_admin"):
        stmt = stmt.where(
            (Ticket.assignee_id == current_user.id) | (Ticket.reporter_id == current_user.id)
        )

    result = await db.execute(stmt)
    count = result.scalar_one_or_none()
    return count if count else 0


async def _get_ticket_status_distribution(
    db: AsyncSession, current_user: User
) -> list[dict]:
    stmt = select(Ticket.status, func.count(Ticket.id).label("count")).group_by(
        Ticket.status
    )

    if current_user.role not in ("super_admin", "org_admin"):
        stmt = stmt.where(
            (Ticket.assignee_id == current_user.id) | (Ticket.reporter_id == current_user.id)
        )

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return []

    total = sum(row.count for row in rows)
    distribution = []
    for row in rows:
        percentage = round((row.count / total) * 100, 1) if total > 0 else 0
        distribution.append(
            {
                "status": row.status,
                "count": row.count,
                "percentage": percentage,
            }
        )

    distribution.sort(key=lambda x: x["count"], reverse=True)
    return distribution


async def _get_project_status_breakdown(
    db: AsyncSession, current_user: User
) -> list[dict]:
    stmt = select(Project.status, func.count(Project.id).label("count")).group_by(
        Project.status
    )

    if current_user.role not in ("super_admin", "org_admin"):
        stmt = stmt.where(Project.owner_id == current_user.id)

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return []

    total = sum(row.count for row in rows)
    breakdown = []
    for row in rows:
        percentage = round((row.count / total) * 100, 1) if total > 0 else 0
        breakdown.append(
            {
                "status": row.status,
                "count": row.count,
                "percentage": percentage,
            }
        )

    breakdown.sort(key=lambda x: x["count"], reverse=True)
    return breakdown


async def _get_recent_activity(db: AsyncSession, limit: int = 10) -> list[dict]:
    stmt = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    entries = result.scalars().all()

    activity_list = []
    for entry in entries:
        user_name = "System"
        if entry.user:
            user_name = entry.user.full_name or entry.user.username or "Unknown"

        timestamp_str = ""
        if entry.created_at:
            timestamp_str = entry.created_at.strftime("%b %d, %Y at %I:%M %p")

        entity_name = entry.details if entry.details else ""

        activity_list.append(
            {
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "entity_name": entity_name,
                "user_name": user_name,
                "timestamp": timestamp_str,
            }
        )

    return activity_list


async def _get_top_contributors(db: AsyncSession, limit: int = 5) -> list[dict]:
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    stmt = (
        select(
            User.id,
            User.username,
            User.email,
            func.coalesce(func.sum(TimeEntry.hours), 0.0).label("total_hours"),
        )
        .join(TimeEntry, TimeEntry.user_id == User.id)
        .where(TimeEntry.spent_date >= start_of_week)
        .group_by(User.id, User.username, User.email)
        .order_by(func.sum(TimeEntry.hours).desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    contributors = []
    for row in rows:
        contributors.append(
            {
                "username": row.username,
                "email": row.email,
                "hours": round(float(row.total_hours), 1),
            }
        )

    return contributors