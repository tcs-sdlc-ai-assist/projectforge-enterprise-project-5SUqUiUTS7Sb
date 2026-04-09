import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy import select

from database import Base, engine, async_session_factory
from main import app
from models.user import User
from models.project import Project, ProjectMember
from models.ticket import Ticket
from models.sprint import Sprint
from models.time_entry import TimeEntry
from models.audit_log import AuditLog
from models.department import Department
from dependencies import create_session, SESSION_COOKIE_NAME

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def admin_user():
    async with async_session_factory() as session:
        user = User(
            username="testadmin",
            email="testadmin@projectforge.local",
            full_name="Test Admin",
            password_hash=pwd_context.hash("password123"),
            role="super_admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def project_manager_user():
    async with async_session_factory() as session:
        user = User(
            username="testpm",
            email="testpm@projectforge.local",
            full_name="Test PM",
            password_hash=pwd_context.hash("password123"),
            role="project_manager",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def developer_user():
    async with async_session_factory() as session:
        user = User(
            username="testdev",
            email="testdev@projectforge.local",
            full_name="Test Developer",
            password_hash=pwd_context.hash("password123"),
            role="developer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def viewer_user():
    async with async_session_factory() as session:
        user = User(
            username="testviewer",
            email="testviewer@projectforge.local",
            full_name="Test Viewer",
            password_hash=pwd_context.hash("password123"),
            role="viewer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def sample_project(admin_user):
    async with async_session_factory() as session:
        project = Project(
            key="TST",
            name="Test Project",
            description="A test project",
            status="active",
            owner_id=admin_user.id,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project


@pytest_asyncio.fixture
async def sample_sprint(sample_project):
    async with async_session_factory() as session:
        sprint = Sprint(
            project_id=sample_project.id,
            name="Sprint 1",
            goal="Test sprint goal",
            status="active",
            start_date=date.today() - timedelta(days=7),
            end_date=date.today() + timedelta(days=7),
        )
        session.add(sprint)
        await session.commit()
        await session.refresh(sprint)
        return sprint


@pytest_asyncio.fixture
async def sample_tickets(sample_project, admin_user, sample_sprint):
    async with async_session_factory() as session:
        tickets = []
        for i, status in enumerate(["backlog", "todo", "in_progress", "in_review", "done"]):
            ticket = Ticket(
                project_id=sample_project.id,
                sprint_id=sample_sprint.id,
                ticket_key=f"TST-{i + 1}",
                title=f"Test Ticket {i + 1}",
                description=f"Description for ticket {i + 1}",
                status=status,
                ticket_type="task",
                priority="medium",
                assignee_id=admin_user.id,
                reporter_id=admin_user.id,
            )
            session.add(ticket)
            tickets.append(ticket)
        await session.commit()
        for t in tickets:
            await session.refresh(t)
        return tickets


@pytest_asyncio.fixture
async def sample_time_entries(sample_tickets, admin_user):
    async with async_session_factory() as session:
        entries = []
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        for i, ticket in enumerate(sample_tickets[:3]):
            entry = TimeEntry(
                ticket_id=ticket.id,
                user_id=admin_user.id,
                hours=float(i + 1),
                description=f"Work on ticket {ticket.ticket_key}",
                spent_date=start_of_week,
            )
            session.add(entry)
            entries.append(entry)
        await session.commit()
        for e in entries:
            await session.refresh(e)
        return entries


@pytest_asyncio.fixture
async def sample_audit_logs(admin_user):
    async with async_session_factory() as session:
        logs = []
        for i in range(5):
            log = AuditLog(
                actor_id=str(admin_user.id),
                action="create" if i % 2 == 0 else "update",
                entity_type="ticket" if i % 2 == 0 else "project",
                entity_id=str(i + 1),
                details=f"Test audit log entry {i + 1}",
            )
            session.add(log)
            logs.append(log)
        await session.commit()
        for log in logs:
            await session.refresh(log)
        return logs


def _auth_cookies(user_id: int) -> dict:
    token = create_session(user_id)
    return {SESSION_COOKIE_NAME: token}


@pytest.mark.asyncio
async def test_dashboard_requires_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code in (302, 401)


@pytest.mark.asyncio
async def test_dashboard_renders_for_super_admin(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_renders_for_project_manager(project_manager_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(project_manager_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_renders_for_developer(developer_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(developer_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_renders_for_viewer(viewer_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(viewer_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_shows_summary_cards(admin_user, sample_project, sample_tickets):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Total Projects" in response.text
        assert "Active Tickets" in response.text
        assert "Hours This Week" in response.text
        assert "Overdue Tickets" in response.text


@pytest.mark.asyncio
async def test_dashboard_project_count_for_admin(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Total Projects" in response.text


@pytest.mark.asyncio
async def test_dashboard_active_tickets_count(admin_user, sample_project, sample_tickets):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Active Tickets" in response.text


@pytest.mark.asyncio
async def test_dashboard_hours_logged_this_week(admin_user, sample_project, sample_tickets, sample_time_entries):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Hours This Week" in response.text
        # Total hours: 1.0 + 2.0 + 3.0 = 6.0
        assert "6.0" in response.text


@pytest.mark.asyncio
async def test_dashboard_overdue_tickets(admin_user):
    async with async_session_factory() as session:
        project = Project(
            key="OVD",
            name="Overdue Project",
            status="active",
            owner_id=admin_user.id,
        )
        session.add(project)
        await session.flush()

        sprint = Sprint(
            project_id=project.id,
            name="Past Sprint",
            status="active",
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() - timedelta(days=1),
        )
        session.add(sprint)
        await session.flush()

        ticket = Ticket(
            project_id=project.id,
            sprint_id=sprint.id,
            ticket_key="OVD-1",
            title="Overdue Ticket",
            status="in_progress",
            ticket_type="task",
            priority="high",
            assignee_id=admin_user.id,
            reporter_id=admin_user.id,
        )
        session.add(ticket)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Overdue Tickets" in response.text


@pytest.mark.asyncio
async def test_dashboard_ticket_status_distribution(admin_user, sample_project, sample_tickets):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Ticket Status Distribution" in response.text


@pytest.mark.asyncio
async def test_dashboard_project_status_breakdown(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Project Status Breakdown" in response.text


@pytest.mark.asyncio
async def test_dashboard_recent_activity_feed(admin_user, sample_audit_logs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Recent Activity" in response.text
        assert "Test audit log entry" in response.text


@pytest.mark.asyncio
async def test_dashboard_recent_activity_shows_user_name(admin_user, sample_audit_logs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Test Admin" in response.text or "testadmin" in response.text


@pytest.mark.asyncio
async def test_dashboard_recent_activity_empty(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Recent Activity" in response.text


@pytest.mark.asyncio
async def test_dashboard_top_contributors(admin_user, sample_project, sample_tickets, sample_time_entries):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Top Contributors" in response.text
        assert "testadmin" in response.text


@pytest.mark.asyncio
async def test_dashboard_top_contributors_empty(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Top Contributors" in response.text
        assert "No time entries this week" in response.text


@pytest.mark.asyncio
async def test_dashboard_new_project_link_for_admin(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "/projects/create" in response.text


@pytest.mark.asyncio
async def test_dashboard_audit_log_link_for_super_admin(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "View full log" in response.text or "/audit-log" in response.text


@pytest.mark.asyncio
async def test_dashboard_no_data_shows_empty_states(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "No ticket data available" in response.text or "No projects created" in response.text


@pytest.mark.asyncio
async def test_dashboard_developer_sees_own_data(developer_user):
    async with async_session_factory() as session:
        project = Project(
            key="DEV",
            name="Dev Project",
            status="active",
            owner_id=developer_user.id,
        )
        session.add(project)
        await session.flush()

        ticket = Ticket(
            project_id=project.id,
            ticket_key="DEV-1",
            title="Dev Ticket",
            status="in_progress",
            ticket_type="task",
            priority="medium",
            assignee_id=developer_user.id,
            reporter_id=developer_user.id,
        )
        session.add(ticket)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(developer_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Active Tickets" in response.text


@pytest.mark.asyncio
async def test_dashboard_multiple_projects(admin_user):
    async with async_session_factory() as session:
        for i in range(3):
            project = Project(
                key=f"MP{i}",
                name=f"Multi Project {i}",
                status="active" if i < 2 else "planning",
                owner_id=admin_user.id,
            )
            session.add(project)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Total Projects" in response.text


@pytest.mark.asyncio
async def test_dashboard_inactive_user_rejected():
    async with async_session_factory() as session:
        user = User(
            username="inactiveuser",
            email="inactive@projectforge.local",
            full_name="Inactive User",
            password_hash=pwd_context.hash("password123"),
            role="super_admin",
            is_active=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(user_id)
        response = await client.get("/dashboard", cookies=cookies, follow_redirects=False)
        assert response.status_code in (302, 401)


@pytest.mark.asyncio
async def test_dashboard_invalid_session_cookie():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = {SESSION_COOKIE_NAME: "invalid-cookie-value"}
        response = await client.get("/dashboard", cookies=cookies, follow_redirects=False)
        assert response.status_code in (302, 401)


@pytest.mark.asyncio
async def test_dashboard_contains_navigation_links(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "/projects" in response.text
        assert "/departments" in response.text
        assert "/users" in response.text
        assert "/audit-log" in response.text


@pytest.mark.asyncio
async def test_dashboard_shows_user_role_badge(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Super Admin" in response.text


@pytest.mark.asyncio
async def test_dashboard_multiple_time_entries_contributors(admin_user, developer_user):
    async with async_session_factory() as session:
        project = Project(
            key="CNT",
            name="Contributor Project",
            status="active",
            owner_id=admin_user.id,
        )
        session.add(project)
        await session.flush()

        ticket = Ticket(
            project_id=project.id,
            ticket_key="CNT-1",
            title="Contributor Ticket",
            status="in_progress",
            ticket_type="task",
            priority="medium",
            assignee_id=admin_user.id,
            reporter_id=admin_user.id,
        )
        session.add(ticket)
        await session.flush()

        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())

        entry1 = TimeEntry(
            ticket_id=ticket.id,
            user_id=admin_user.id,
            hours=5.0,
            description="Admin work",
            spent_date=start_of_week,
        )
        entry2 = TimeEntry(
            ticket_id=ticket.id,
            user_id=developer_user.id,
            hours=3.0,
            description="Dev work",
            spent_date=start_of_week,
        )
        session.add(entry1)
        session.add(entry2)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookies = _auth_cookies(admin_user.id)
        response = await client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert "Top Contributors" in response.text
        assert "testadmin" in response.text
        assert "testdev" in response.text


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app"] == "ProjectForge"