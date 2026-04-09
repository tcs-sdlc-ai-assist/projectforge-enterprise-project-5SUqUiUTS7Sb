import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from dependencies import get_db, create_session, SESSION_COOKIE_NAME
from models.user import User
from models.department import Department
from models.project import Project, ProjectMember
from models.sprint import Sprint
from models.ticket import Ticket
from models.label import Label
from models.comment import Comment
from models.time_entry import TimeEntry
from models.audit_log import AuditLog

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

test_async_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


async def _override_get_db():
    async with test_async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from main import app

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


async def _create_user(
    db: AsyncSession,
    username: str,
    role: str,
    password: str = "testpassword123",
    email: str | None = None,
    full_name: str | None = None,
) -> User:
    if email is None:
        email = f"{username}@test.projectforge.local"
    if full_name is None:
        full_name = username.replace("_", " ").title()

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=pwd_context.hash(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def super_admin_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, "testadmin", "super_admin")
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def project_manager_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, "testpm", "project_manager")
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def developer_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, "testdev", "developer")
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def team_lead_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, "testtl", "team_lead")
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, "testviewer", "viewer")
    await db_session.commit()
    return user


def _make_session_cookie(user: User) -> dict[str, str]:
    cookie_value = create_session(user.id)
    return {SESSION_COOKIE_NAME: cookie_value}


@pytest_asyncio.fixture
async def authenticated_client(
    client: AsyncClient,
    super_admin_user: User,
) -> AsyncClient:
    cookies = _make_session_cookie(super_admin_user)
    client.cookies.update(cookies)
    return client


@pytest_asyncio.fixture
async def pm_client(
    client: AsyncClient,
    project_manager_user: User,
) -> AsyncClient:
    cookies = _make_session_cookie(project_manager_user)
    client.cookies.update(cookies)
    return client


@pytest_asyncio.fixture
async def dev_client(
    client: AsyncClient,
    developer_user: User,
) -> AsyncClient:
    cookies = _make_session_cookie(developer_user)
    client.cookies.update(cookies)
    return client


@pytest_asyncio.fixture
async def tl_client(
    client: AsyncClient,
    team_lead_user: User,
) -> AsyncClient:
    cookies = _make_session_cookie(team_lead_user)
    client.cookies.update(cookies)
    return client


@pytest_asyncio.fixture
async def viewer_client(
    client: AsyncClient,
    viewer_user: User,
) -> AsyncClient:
    cookies = _make_session_cookie(viewer_user)
    client.cookies.update(cookies)
    return client


@pytest_asyncio.fixture
async def test_department(db_session: AsyncSession) -> Department:
    department = Department(
        name="Test Engineering",
        code="TENG",
        description="Test engineering department",
    )
    db_session.add(department)
    await db_session.flush()
    await db_session.refresh(department)
    await db_session.commit()
    return department


@pytest_asyncio.fixture
async def test_project(
    db_session: AsyncSession,
    super_admin_user: User,
) -> Project:
    project = Project(
        key="TEST",
        name="Test Project",
        description="A test project for unit tests",
        status="active",
        owner_id=super_admin_user.id,
    )
    db_session.add(project)
    await db_session.flush()
    await db_session.refresh(project)

    member = ProjectMember(
        project_id=project.id,
        user_id=super_admin_user.id,
        role="project_manager",
    )
    db_session.add(member)
    await db_session.flush()
    await db_session.commit()
    return project