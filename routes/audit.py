import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dependencies import (
    get_db,
    get_current_user,
    require_role,
    get_template_context,
    clear_flashes,
)
from models.audit_log import AuditLog
from models.user import User
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

PER_PAGE = 25


@router.get("/audit-log")
async def audit_log_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin"]))],
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    stmt = select(AuditLog).options(selectinload(AuditLog.user))

    if action:
        stmt = stmt.where(AuditLog.action == action)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)

    if actor:
        stmt = stmt.where(AuditLog.actor_id == actor)

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            stmt = stmt.where(AuditLog.created_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
            dt_to = dt_to.replace(hour=23, minute=59, second=59)
            stmt = stmt.where(AuditLog.created_at <= dt_to)
        except ValueError:
            pass

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total_entries = count_result.scalar() or 0

    total_pages = max(1, (total_entries + PER_PAGE - 1) // PER_PAGE)

    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PER_PAGE

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(PER_PAGE)

    result = await db.execute(stmt)
    entries = result.scalars().all()

    users_result = await db.execute(select(User).order_by(User.username))
    users = users_result.scalars().all()

    filters = {
        "action": action or "",
        "entity_type": entity_type or "",
        "actor": actor or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
    }

    context = get_template_context(
        request,
        current_user=current_user,
        entries=entries,
        users=users,
        filters=filters,
        page=page,
        per_page=PER_PAGE,
        total_entries=total_entries,
        total_pages=total_pages,
    )

    response = templates.TemplateResponse(request, "audit/list.html", context=context)
    clear_flashes(response)
    return response