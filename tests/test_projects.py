import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from database import Base, engine, async_session_factory
from main import app
from models.user import User
from models.project import Project, ProjectMember
from models.department import Department
from models.sprint import Sprint
from models.ticket import Ticket
from passlib.context import CryptContext

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
            username="adminuser",
            email="admin@test.local",
            full_name="Admin User",
            password_hash=pwd_context.hash("password123"),
            role="super_admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def manager_user():
    async with async_session_factory() as session:
        user = User(
            username="manageruser",
            email="manager@test.local",
            full_name="Manager User",
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
            username="devuser",
            email="dev@test.local",
            full_name="Developer User",
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
            username="vieweruser",
            email="viewer@test.local",
            full_name="Viewer User",
            password_hash=pwd_context.hash("password123"),
            role="viewer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def department():
    async with async_session_factory() as session:
        dept = Department(
            name="Engineering",
            code="ENG",
            description="Engineering department",
        )
        session.add(dept)
        await session.commit()
        await session.refresh(dept)
        return dept


@pytest_asyncio.fixture
async def sample_project(admin_user):
    async with async_session_factory() as session:
        project = Project(
            key="TEST",
            name="Test Project",
            description="A test project",
            status="planning",
            owner_id=admin_user.id,
        )
        session.add(project)
        await session.flush()
        member = ProjectMember(
            project_id=project.id,
            user_id=admin_user.id,
            role="project_manager",
        )
        session.add(member)
        await session.commit()
        await session.refresh(project)
        return project


async def login_user(client: AsyncClient, username: str, password: str = "password123"):
    response = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    return response


@pytest.mark.asyncio
async def test_create_project_auto_assigns_owner(admin_user, department):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            "/projects/create",
            data={
                "name": "New Project",
                "description": "A brand new project",
                "status": "planning",
                "department_id": str(department.id),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.name == "New Project")
            )
            project = result.scalar_one_or_none()
            assert project is not None
            assert project.owner_id == admin_user.id
            assert project.department_id == department.id
            assert project.status == "planning"
            assert project.key is not None and len(project.key) > 0

            member_result = await session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == admin_user.id,
                )
            )
            member = member_result.scalar_one_or_none()
            assert member is not None
            assert member.role == "project_manager"


@pytest.mark.asyncio
async def test_create_project_generates_unique_key(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        await client.post(
            "/projects/create",
            data={"name": "Alpha Beta", "description": "", "status": "planning", "department_id": ""},
            follow_redirects=False,
        )
        await client.post(
            "/projects/create",
            data={"name": "Alpha Bravo", "description": "", "status": "planning", "department_id": ""},
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(select(Project).order_by(Project.id))
            projects = result.scalars().all()
            keys = [p.key for p in projects]
            assert len(keys) == len(set(keys)), "Project keys must be unique"


@pytest.mark.asyncio
async def test_create_project_duplicate_name_fails(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            "/projects/create",
            data={
                "name": "Test Project",
                "description": "Duplicate",
                "status": "planning",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_edit_project(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            f"/projects/{sample_project.id}/edit",
            data={
                "name": "Updated Project Name",
                "description": "Updated description",
                "status": "active",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.id == sample_project.id)
            )
            project = result.scalar_one_or_none()
            assert project is not None
            assert project.name == "Updated Project Name"
            assert project.description == "Updated description"
            assert project.status == "active"


@pytest.mark.asyncio
async def test_edit_project_empty_name_fails(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            f"/projects/{sample_project.id}/edit",
            data={
                "name": "   ",
                "description": "",
                "status": "active",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_delete_project(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            f"/projects/{sample_project.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.id == sample_project.id)
            )
            project = result.scalar_one_or_none()
            assert project is None


@pytest.mark.asyncio
async def test_delete_project_forbidden_for_developer(admin_user, developer_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "devuser")

        response = await client.post(
            f"/projects/{sample_project.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code in (403, 302)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.id == sample_project.id)
            )
            project = result.scalar_one_or_none()
            assert project is not None


@pytest.mark.asyncio
async def test_project_detail_page(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            f"/projects/{sample_project.id}",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Test Project" in response.text


@pytest.mark.asyncio
async def test_project_detail_not_found(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            "/projects/99999",
            follow_redirects=False,
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_projects(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get("/projects", follow_redirects=False)
        assert response.status_code == 200
        assert "Test Project" in response.text


@pytest.mark.asyncio
async def test_list_projects_filter_by_status(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            "/projects?status=planning",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Test Project" in response.text

        response = await client.get(
            "/projects?status=archived",
            follow_redirects=False,
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_projects_search(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            "/projects?search=Test",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Test Project" in response.text

        response = await client.get(
            "/projects?search=NonExistentProject",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Test Project" not in response.text


@pytest.mark.asyncio
async def test_add_project_member(admin_user, developer_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            f"/projects/{sample_project.id}/members/add",
            data={
                "user_id": str(developer_user.id),
                "role": "developer",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == sample_project.id,
                    ProjectMember.user_id == developer_user.id,
                )
            )
            member = result.scalar_one_or_none()
            assert member is not None
            assert member.role == "developer"


@pytest.mark.asyncio
async def test_add_duplicate_member_fails(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            f"/projects/{sample_project.id}/members/add",
            data={
                "user_id": str(admin_user.id),
                "role": "developer",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303


@pytest.mark.asyncio
async def test_remove_project_member(admin_user, developer_user, sample_project):
    async with async_session_factory() as session:
        member = ProjectMember(
            project_id=sample_project.id,
            user_id=developer_user.id,
            role="developer",
        )
        session.add(member)
        await session.commit()
        await session.refresh(member)
        member_id = member.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            f"/projects/{sample_project.id}/members/{member_id}/remove",
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(ProjectMember).where(ProjectMember.id == member_id)
            )
            removed = result.scalar_one_or_none()
            assert removed is None


@pytest.mark.asyncio
async def test_project_members_page(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            f"/projects/{sample_project.id}/members",
            follow_redirects=False,
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_project_status_workflow(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        for new_status in ["active", "on_hold", "completed", "archived"]:
            response = await client.post(
                f"/projects/{sample_project.id}/edit",
                data={
                    "name": "Test Project",
                    "description": "A test project",
                    "status": new_status,
                    "department_id": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            async with async_session_factory() as session:
                result = await session.execute(
                    select(Project).where(Project.id == sample_project.id)
                )
                project = result.scalar_one()
                assert project.status == new_status


@pytest.mark.asyncio
async def test_kanban_board_renders(admin_user, sample_project):
    async with async_session_factory() as session:
        for i, status in enumerate(["backlog", "todo", "in_progress", "in_review", "done"]):
            ticket = Ticket(
                project_id=sample_project.id,
                ticket_key=f"TEST-{i + 1}",
                title=f"Ticket {status}",
                status=status,
                ticket_type="task",
                priority="medium",
                reporter_id=admin_user.id,
            )
            session.add(ticket)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            f"/projects/{sample_project.id}/board",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Kanban Board" in response.text
        assert "Ticket backlog" in response.text
        assert "Ticket todo" in response.text
        assert "Ticket in_progress" in response.text


@pytest.mark.asyncio
async def test_kanban_board_filter_by_assignee(admin_user, developer_user, sample_project):
    async with async_session_factory() as session:
        member = ProjectMember(
            project_id=sample_project.id,
            user_id=developer_user.id,
            role="developer",
        )
        session.add(member)
        await session.flush()

        ticket1 = Ticket(
            project_id=sample_project.id,
            ticket_key="TEST-10",
            title="Assigned Ticket",
            status="todo",
            ticket_type="task",
            priority="medium",
            reporter_id=admin_user.id,
            assignee_id=developer_user.id,
        )
        ticket2 = Ticket(
            project_id=sample_project.id,
            ticket_key="TEST-11",
            title="Unassigned Ticket",
            status="todo",
            ticket_type="task",
            priority="medium",
            reporter_id=admin_user.id,
            assignee_id=None,
        )
        session.add_all([ticket1, ticket2])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            f"/projects/{sample_project.id}/board?assignee_id={developer_user.id}",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Assigned Ticket" in response.text
        assert "Unassigned Ticket" not in response.text


@pytest.mark.asyncio
async def test_kanban_board_drag_drop_status_update(admin_user, sample_project):
    async with async_session_factory() as session:
        ticket = Ticket(
            project_id=sample_project.id,
            ticket_key="TEST-20",
            title="Drag Drop Ticket",
            status="backlog",
            ticket_type="task",
            priority="medium",
            reporter_id=admin_user.id,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        ticket_id = ticket.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.patch(
            f"/api/projects/{sample_project.id}/tickets/{ticket_id}/status",
            json={"status": "in_progress"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "in_progress"

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket_id)
            )
            updated_ticket = result.scalar_one()
            assert updated_ticket.status == "in_progress"


@pytest.mark.asyncio
async def test_kanban_board_invalid_status_update(admin_user, sample_project):
    async with async_session_factory() as session:
        ticket = Ticket(
            project_id=sample_project.id,
            ticket_key="TEST-21",
            title="Invalid Status Ticket",
            status="backlog",
            ticket_type="task",
            priority="medium",
            reporter_id=admin_user.id,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        ticket_id = ticket.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.patch(
            f"/api/projects/{sample_project.id}/tickets/{ticket_id}/status",
            json={"status": "invalid_status"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_rbac_viewer_cannot_create_project(viewer_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "vieweruser")

        response = await client.post(
            "/projects/create",
            data={
                "name": "Viewer Project",
                "description": "Should fail",
                "status": "planning",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code in (403, 302)


@pytest.mark.asyncio
async def test_rbac_viewer_cannot_edit_project(admin_user, viewer_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "vieweruser")

        response = await client.post(
            f"/projects/{sample_project.id}/edit",
            data={
                "name": "Hacked Name",
                "description": "Hacked",
                "status": "active",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code in (403, 302)


@pytest.mark.asyncio
async def test_rbac_developer_cannot_delete_project(admin_user, developer_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "devuser")

        response = await client.post(
            f"/projects/{sample_project.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code in (403, 302)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.id == sample_project.id)
            )
            assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_rbac_developer_cannot_add_member(admin_user, developer_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "devuser")

        response = await client.post(
            f"/projects/{sample_project.id}/members/add",
            data={
                "user_id": str(developer_user.id),
                "role": "developer",
            },
            follow_redirects=False,
        )
        assert response.status_code in (403, 302)


@pytest.mark.asyncio
async def test_rbac_project_manager_can_create_project(manager_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "manageruser")

        response = await client.post(
            "/projects/create",
            data={
                "name": "Manager Project",
                "description": "Created by PM",
                "status": "planning",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.name == "Manager Project")
            )
            project = result.scalar_one_or_none()
            assert project is not None
            assert project.owner_id == manager_user.id


@pytest.mark.asyncio
async def test_unauthenticated_access_redirects(sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/projects", follow_redirects=False)
        assert response.status_code in (302, 401)

        response = await client.get(
            f"/projects/{sample_project.id}",
            follow_redirects=False,
        )
        assert response.status_code in (302, 401)

        response = await client.post(
            "/projects/create",
            data={"name": "Unauth Project", "description": "", "status": "planning", "department_id": ""},
            follow_redirects=False,
        )
        assert response.status_code in (302, 401)


@pytest.mark.asyncio
async def test_create_project_form_renders(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get("/projects/create", follow_redirects=False)
        assert response.status_code == 200
        assert "Create" in response.text


@pytest.mark.asyncio
async def test_edit_project_form_renders(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            f"/projects/{sample_project.id}/edit",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Test Project" in response.text


@pytest.mark.asyncio
async def test_kanban_board_empty_project(admin_user, sample_project):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.get(
            f"/projects/{sample_project.id}/board",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Kanban Board" in response.text
        assert "No tickets" in response.text


@pytest.mark.asyncio
async def test_project_invalid_status_defaults(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "adminuser")

        response = await client.post(
            "/projects/create",
            data={
                "name": "Invalid Status Project",
                "description": "",
                "status": "nonexistent_status",
                "department_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Project).where(Project.name == "Invalid Status Project")
            )
            project = result.scalar_one_or_none()
            assert project is not None
            assert project.status == "planning"