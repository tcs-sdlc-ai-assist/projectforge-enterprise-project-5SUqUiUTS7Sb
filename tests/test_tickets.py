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
from models.sprint import Sprint
from models.ticket import Ticket
from models.comment import Comment
from models.time_entry import TimeEntry
from models.label import Label
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
            username="adminticket",
            email="adminticket@test.com",
            full_name="Admin Ticket",
            password_hash=pwd_context.hash("password123"),
            role="super_admin",
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
            username="devticket",
            email="devticket@test.com",
            full_name="Dev Ticket",
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
            username="viewerticket",
            email="viewerticket@test.com",
            full_name="Viewer Ticket",
            password_hash=pwd_context.hash("password123"),
            role="viewer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def project_with_members(admin_user, developer_user):
    async with async_session_factory() as session:
        project = Project(
            key="TPROJ",
            name="Ticket Test Project",
            description="Project for ticket tests",
            status="active",
            owner_id=admin_user.id,
        )
        session.add(project)
        await session.flush()

        member_admin = ProjectMember(
            project_id=project.id,
            user_id=admin_user.id,
            role="project_manager",
        )
        member_dev = ProjectMember(
            project_id=project.id,
            user_id=developer_user.id,
            role="developer",
        )
        session.add(member_admin)
        session.add(member_dev)
        await session.commit()
        await session.refresh(project)
        return project


@pytest_asyncio.fixture
async def sprint(project_with_members):
    async with async_session_factory() as session:
        s = Sprint(
            project_id=project_with_members.id,
            name="Sprint 1",
            goal="Test sprint",
            status="active",
            start_date="2025-01-01",
            end_date="2025-01-14",
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s


@pytest_asyncio.fixture
async def label(project_with_members):
    async with async_session_factory() as session:
        lbl = Label(
            project_id=project_with_members.id,
            name="bug-label",
            color="#ff0000",
        )
        session.add(lbl)
        await session.commit()
        await session.refresh(lbl)
        return lbl


async def login_user(client: AsyncClient, username: str, password: str = "password123"):
    response = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    return response


@pytest_asyncio.fixture
async def admin_client(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, admin_user.username)
        yield client


@pytest_asyncio.fixture
async def dev_client(developer_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, developer_user.username)
        yield client


@pytest_asyncio.fixture
async def viewer_client(viewer_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, viewer_user.username)
        yield client


async def create_ticket_via_post(
    client: AsyncClient,
    project_id: int,
    title: str = "Test Ticket",
    ticket_type: str = "task",
    priority: str = "medium",
    description: str = "Test description",
    assignee_id: str = "",
    sprint_id: str = "",
    parent_id: str = "",
    story_points: str = "",
    label_ids: list = None,
):
    data = {
        "title": title,
        "ticket_type": ticket_type,
        "priority": priority,
        "description": description,
        "assignee_id": assignee_id,
        "sprint_id": sprint_id,
        "parent_id": parent_id,
        "story_points": story_points,
    }
    if label_ids:
        data["label_ids"] = label_ids
    response = await client.post(
        f"/projects/{project_id}/tickets/create",
        data=data,
        follow_redirects=False,
    )
    return response


class TestTicketCreation:
    @pytest.mark.asyncio
    async def test_create_ticket_auto_generated_key(
        self, admin_client, project_with_members
    ):
        response = await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="First Ticket",
            ticket_type="bug",
            priority="high",
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "First Ticket")
            )
            ticket = result.scalar_one_or_none()
            assert ticket is not None
            assert ticket.ticket_key == "TPROJ-1"
            assert ticket.ticket_type == "bug"
            assert ticket.priority == "high"
            assert ticket.status == "backlog"

    @pytest.mark.asyncio
    async def test_create_multiple_tickets_sequential_keys(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Ticket One"
        )
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Ticket Two"
        )
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Ticket Three"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket)
                .where(Ticket.project_id == project_with_members.id)
                .order_by(Ticket.id)
            )
            tickets = result.scalars().all()
            assert len(tickets) == 3
            assert tickets[0].ticket_key == "TPROJ-1"
            assert tickets[1].ticket_key == "TPROJ-2"
            assert tickets[2].ticket_key == "TPROJ-3"

    @pytest.mark.asyncio
    async def test_create_ticket_with_sprint_and_assignee(
        self, admin_client, project_with_members, sprint, developer_user
    ):
        response = await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Sprint Ticket",
            sprint_id=str(sprint.id),
            assignee_id=str(developer_user.id),
            story_points="5",
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Sprint Ticket")
            )
            ticket = result.scalar_one_or_none()
            assert ticket is not None
            assert ticket.sprint_id == sprint.id
            assert ticket.assignee_id == developer_user.id
            assert ticket.story_points == 5

    @pytest.mark.asyncio
    async def test_create_ticket_with_labels(
        self, admin_client, project_with_members, label
    ):
        response = await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Labeled Ticket",
            label_ids=[str(label.id)],
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(Ticket)
                .where(Ticket.title == "Labeled Ticket")
                .options(selectinload(Ticket.labels))
            )
            ticket = result.scalar_one_or_none()
            assert ticket is not None
            assert len(ticket.labels) == 1
            assert ticket.labels[0].id == label.id

    @pytest.mark.asyncio
    async def test_create_ticket_developer_allowed(
        self, dev_client, project_with_members
    ):
        response = await create_ticket_via_post(
            dev_client,
            project_with_members.id,
            title="Dev Ticket",
        )
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_create_ticket_viewer_forbidden(
        self, viewer_client, project_with_members
    ):
        response = await create_ticket_via_post(
            viewer_client,
            project_with_members.id,
            title="Viewer Ticket",
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_ticket_form_page(
        self, admin_client, project_with_members
    ):
        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets/create"
        )
        assert response.status_code == 200
        assert "Create Ticket" in response.text


class TestTicketEdit:
    @pytest.mark.asyncio
    async def test_edit_ticket(self, admin_client, project_with_members):
        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Original Title",
            ticket_type="task",
            priority="low",
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Original Title")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/edit",
            data={
                "title": "Updated Title",
                "ticket_type": "bug",
                "priority": "critical",
                "description": "Updated description",
                "status": "in_progress",
                "assignee_id": "",
                "sprint_id": "",
                "parent_id": "",
                "story_points": "8",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket.id)
            )
            updated = result.scalar_one()
            assert updated.title == "Updated Title"
            assert updated.ticket_type == "bug"
            assert updated.priority == "critical"
            assert updated.status == "in_progress"
            assert updated.story_points == 8

    @pytest.mark.asyncio
    async def test_edit_ticket_form_page(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Edit Form Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Edit Form Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/edit"
        )
        assert response.status_code == 200
        assert "Edit Form Ticket" in response.text


class TestTicketStatusTransitions:
    @pytest.mark.asyncio
    async def test_change_status(self, admin_client, project_with_members):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Status Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Status Ticket")
            )
            ticket = result.scalar_one()
            assert ticket.status == "backlog"

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/status",
            data={"status": "in_progress"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket.id)
            )
            updated = result.scalar_one()
            assert updated.status == "in_progress"

    @pytest.mark.asyncio
    async def test_change_status_to_closed(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Close Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Close Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/status",
            data={"status": "closed"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket.id)
            )
            updated = result.scalar_one()
            assert updated.status == "closed"

    @pytest.mark.asyncio
    async def test_change_status_invalid(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Invalid Status Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Invalid Status Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/status",
            data={"status": "nonexistent_status"},
            follow_redirects=False,
        )
        assert response.status_code == 400


class TestSubtasks:
    @pytest.mark.asyncio
    async def test_create_subtask(self, admin_client, project_with_members):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Parent Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Parent Ticket")
            )
            parent = result.scalar_one()

        response = await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Child Ticket",
            parent_id=str(parent.id),
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Child Ticket")
            )
            child = result.scalar_one()
            assert child.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_subtasks_shown_on_detail(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Parent Detail"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Parent Detail")
            )
            parent = result.scalar_one()

        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Sub Detail",
            parent_id=str(parent.id),
        )

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets/{parent.id}"
        )
        assert response.status_code == 200
        assert "Sub Detail" in response.text


class TestComments:
    @pytest.mark.asyncio
    async def test_add_comment(self, admin_client, project_with_members):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Comment Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Comment Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments",
            data={"content": "This is a test comment", "is_internal": ""},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Comment).where(Comment.ticket_id == ticket.id)
            )
            comments = result.scalars().all()
            assert len(comments) == 1
            assert comments[0].content == "This is a test comment"
            assert comments[0].is_internal is False

    @pytest.mark.asyncio
    async def test_add_internal_comment(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Internal Comment Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Internal Comment Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments",
            data={"content": "Internal note", "is_internal": "true"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Comment).where(Comment.ticket_id == ticket.id)
            )
            comments = result.scalars().all()
            assert len(comments) == 1
            assert comments[0].is_internal is True

    @pytest.mark.asyncio
    async def test_add_empty_comment_rejected(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Empty Comment Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Empty Comment Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments",
            data={"content": "   ", "is_internal": ""},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Comment).where(Comment.ticket_id == ticket.id)
            )
            comments = result.scalars().all()
            assert len(comments) == 0

    @pytest.mark.asyncio
    async def test_delete_own_comment(
        self, admin_client, project_with_members, admin_user
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Delete Comment Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Delete Comment Ticket")
            )
            ticket = result.scalar_one()

        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments",
            data={"content": "To be deleted", "is_internal": ""},
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Comment).where(Comment.ticket_id == ticket.id)
            )
            comment = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments/{comment.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Comment).where(Comment.id == comment.id)
            )
            deleted = result.scalar_one_or_none()
            assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_other_user_comment_forbidden(
        self, dev_client, admin_client, project_with_members, admin_user
    ):
        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/create",
            data={
                "title": "Cross Comment Ticket",
                "ticket_type": "task",
                "priority": "medium",
                "description": "",
                "assignee_id": "",
                "sprint_id": "",
                "parent_id": "",
                "story_points": "",
            },
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Cross Comment Ticket")
            )
            ticket = result.scalar_one()

        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments",
            data={"content": "Admin comment", "is_internal": ""},
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Comment).where(Comment.ticket_id == ticket.id)
            )
            comment = result.scalar_one()

        response = await dev_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/comments/{comment.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 403


class TestTimeEntries:
    @pytest.mark.asyncio
    async def test_add_time_entry(self, admin_client, project_with_members):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Time Entry Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Time Entry Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries",
            data={
                "hours": "2.5",
                "spent_date": "2025-01-10",
                "description": "Worked on feature",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(TimeEntry).where(TimeEntry.ticket_id == ticket.id)
            )
            entries = result.scalars().all()
            assert len(entries) == 1
            assert entries[0].hours == 2.5
            assert entries[0].description == "Worked on feature"

    @pytest.mark.asyncio
    async def test_add_time_entry_invalid_hours(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Invalid Hours Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Invalid Hours Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries",
            data={
                "hours": "-1",
                "spent_date": "2025-01-10",
                "description": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(TimeEntry).where(TimeEntry.ticket_id == ticket.id)
            )
            entries = result.scalars().all()
            assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_delete_own_time_entry(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Delete Time Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Delete Time Ticket")
            )
            ticket = result.scalar_one()

        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries",
            data={
                "hours": "1.0",
                "spent_date": "2025-01-10",
                "description": "To delete",
            },
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(TimeEntry).where(TimeEntry.ticket_id == ticket.id)
            )
            entry = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries/{entry.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(TimeEntry).where(TimeEntry.id == entry.id)
            )
            deleted = result.scalar_one_or_none()
            assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_other_user_time_entry_forbidden(
        self, dev_client, admin_client, project_with_members
    ):
        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/create",
            data={
                "title": "Cross Time Ticket",
                "ticket_type": "task",
                "priority": "medium",
                "description": "",
                "assignee_id": "",
                "sprint_id": "",
                "parent_id": "",
                "story_points": "",
            },
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Cross Time Ticket")
            )
            ticket = result.scalar_one()

        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries",
            data={
                "hours": "3.0",
                "spent_date": "2025-01-10",
                "description": "Admin time",
            },
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(TimeEntry).where(TimeEntry.ticket_id == ticket.id)
            )
            entry = result.scalar_one()

        response = await dev_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries/{entry.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 403


class TestTicketDetail:
    @pytest.mark.asyncio
    async def test_ticket_detail_page(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Detail Page Ticket",
            description="Detailed description here",
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Detail Page Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}"
        )
        assert response.status_code == 200
        assert "Detail Page Ticket" in response.text
        assert "TPROJ-1" in response.text
        assert "Detailed description here" in response.text

    @pytest.mark.asyncio
    async def test_ticket_detail_shows_time_entries(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Time Detail Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Time Detail Ticket")
            )
            ticket = result.scalar_one()

        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/time-entries",
            data={
                "hours": "4.0",
                "spent_date": "2025-01-15",
                "description": "Coding session",
            },
            follow_redirects=False,
        )

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}"
        )
        assert response.status_code == 200
        assert "Coding session" in response.text


class TestTicketList:
    @pytest.mark.asyncio
    async def test_list_tickets(self, admin_client, project_with_members):
        for i in range(5):
            await create_ticket_via_post(
                admin_client,
                project_with_members.id,
                title=f"List Ticket {i}",
            )

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets"
        )
        assert response.status_code == 200
        for i in range(5):
            assert f"List Ticket {i}" in response.text

    @pytest.mark.asyncio
    async def test_list_tickets_filter_by_status(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Backlog Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Backlog Ticket")
            )
            ticket = result.scalar_one()

        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/status",
            data={"status": "in_progress"},
            follow_redirects=False,
        )

        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Still Backlog"
        )

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets?status=in_progress"
        )
        assert response.status_code == 200
        assert "Backlog Ticket" in response.text

    @pytest.mark.asyncio
    async def test_list_tickets_filter_by_priority(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Critical Ticket",
            priority="critical",
        )
        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Low Ticket",
            priority="low",
        )

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets?priority=critical"
        )
        assert response.status_code == 200
        assert "Critical Ticket" in response.text

    @pytest.mark.asyncio
    async def test_list_tickets_search(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Unique Search Term Alpha",
        )
        await create_ticket_via_post(
            admin_client,
            project_with_members.id,
            title="Another Ticket Beta",
        )

        response = await admin_client.get(
            f"/projects/{project_with_members.id}/tickets?search=Alpha"
        )
        assert response.status_code == 200
        assert "Unique Search Term Alpha" in response.text


class TestTicketDelete:
    @pytest.mark.asyncio
    async def test_delete_ticket_admin(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Delete Me Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Delete Me Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket.id)
            )
            deleted = result.scalar_one_or_none()
            assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_ticket_developer_forbidden(
        self, dev_client, admin_client, project_with_members
    ):
        await admin_client.post(
            f"/projects/{project_with_members.id}/tickets/create",
            data={
                "title": "No Delete Ticket",
                "ticket_type": "task",
                "priority": "medium",
                "description": "",
                "assignee_id": "",
                "sprint_id": "",
                "parent_id": "",
                "story_points": "",
            },
            follow_redirects=False,
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "No Delete Ticket")
            )
            ticket = result.scalar_one()

        response = await dev_client.post(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 403


class TestTicketRBAC:
    @pytest.mark.asyncio
    async def test_unauthenticated_access_redirects(self, project_with_members):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/projects/{project_with_members.id}/tickets",
                follow_redirects=False,
            )
            assert response.status_code in (302, 401)

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_ticket(
        self, viewer_client, project_with_members
    ):
        response = await viewer_client.get(
            f"/projects/{project_with_members.id}/tickets/create",
            follow_redirects=False,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_edit_ticket(
        self, viewer_client, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Viewer Edit Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Viewer Edit Ticket")
            )
            ticket = result.scalar_one()

        response = await viewer_client.get(
            f"/projects/{project_with_members.id}/tickets/{ticket.id}/edit",
            follow_redirects=False,
        )
        assert response.status_code == 403


class TestKanbanBoardStatusUpdate:
    @pytest.mark.asyncio
    async def test_api_update_ticket_status(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Kanban Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Kanban Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.patch(
            f"/api/projects/{project_with_members.id}/tickets/{ticket.id}/status",
            json={"status": "in_progress"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "in_progress"

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket.id)
            )
            updated = result.scalar_one()
            assert updated.status == "in_progress"

    @pytest.mark.asyncio
    async def test_api_update_ticket_status_invalid(
        self, admin_client, project_with_members
    ):
        await create_ticket_via_post(
            admin_client, project_with_members.id, title="Invalid Kanban Ticket"
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Ticket).where(Ticket.title == "Invalid Kanban Ticket")
            )
            ticket = result.scalar_one()

        response = await admin_client.patch(
            f"/api/projects/{project_with_members.id}/tickets/{ticket.id}/status",
            json={"status": "invalid_status"},
        )
        assert response.status_code == 400