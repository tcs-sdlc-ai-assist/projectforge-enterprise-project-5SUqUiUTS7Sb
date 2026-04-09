import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import settings
from database import init_db
from dependencies import get_optional_user, get_db, get_template_context, clear_flashes
from seed import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ProjectForge application...")
    await init_db()
    logger.info("Database tables created successfully.")
    await seed_database()
    logger.info("Database seeding completed.")
    yield
    logger.info("Shutting down ProjectForge application...")


app = FastAPI(
    title="ProjectForge",
    description="AI-Powered Project Management Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from routes import (
    auth_router,
    dashboard_router,
    departments_router,
    projects_router,
    sprints_router,
    tickets_router,
    labels_router,
    users_router,
    audit_router,
)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(departments_router)
app.include_router(projects_router)
app.include_router(sprints_router)
app.include_router(tickets_router)
app.include_router(labels_router)
app.include_router(users_router)
app.include_router(audit_router)


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    from database import async_session_factory
    from dependencies import get_optional_user as _get_optional_user

    current_user = None
    try:
        async with async_session_factory() as db:
            current_user = await _get_optional_user(request, db)
    except Exception:
        current_user = None

    context = get_template_context(request, current_user=current_user)
    response = templates.TemplateResponse(request, "landing.html", context=context)
    clear_flashes(response)
    return response


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        current_user = None
        try:
            async with async_session_factory() as db:
                from dependencies import get_optional_user as _get_optional_user
                current_user = await _get_optional_user(request, db)
        except Exception:
            current_user = None

        context = get_template_context(request, current_user=current_user)
        response = templates.TemplateResponse(
            request, "errors/404.html", context=context, status_code=404
        )
        clear_flashes(response)
        return response

    if exc.status_code == 401:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=302)

    if exc.status_code == 403:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=403,
            content={"detail": exc.detail or "Forbidden"},
        )

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail or "An error occurred"},
    )


from database import async_session_factory


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "ProjectForge", "version": "1.0.0"}