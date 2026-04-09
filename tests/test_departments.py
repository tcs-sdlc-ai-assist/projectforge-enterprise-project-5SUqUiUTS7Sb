import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from database import Base, engine, async_session_factory
from main import app
from models.department import Department
from models.user import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def create_user(
    username: str = "admin",
    password: str = "adminpass123",
    role: str = "super_admin",
    is_active: bool = True,
    department_id: int = None,
) -> User:
    async with async_session_factory() as session:
        user = User(
            username=username,
            email=f"{username}@projectforge.local",
            full_name=f"{username.title()} User",
            password_hash=pwd_context.hash(password),
            role=role,
            is_active=is_active,
            department_id=department_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def create_department(
    name: str = "Engineering",
    code: str = "ENG",
    description: str = "Engineering department",
    head_id: int = None,
) -> Department:
    async with async_session_factory() as session:
        dept = Department(
            name=name,
            code=code,
            description=description,
            head_id=head_id,
        )
        session.add(dept)
        await session.commit()
        await session.refresh(dept)
        return dept


async def login_user(client: AsyncClient, username: str, password: str) -> None:
    response = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302, f"Login failed: {response.status_code}"


@pytest.mark.asyncio
async def test_create_department_success():
    await create_user(username="admin", password="adminpass123", role="super_admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            "/departments",
            data={
                "name": "Marketing",
                "code": "MKT",
                "description": "Marketing department",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/departments"

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.code == "MKT")
            )
            dept = result.scalar_one_or_none()
            assert dept is not None
            assert dept.name == "Marketing"
            assert dept.code == "MKT"
            assert dept.description == "Marketing department"


@pytest.mark.asyncio
async def test_create_department_duplicate_name():
    await create_user(username="admin", password="adminpass123", role="super_admin")
    await create_department(name="Engineering", code="ENG")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            "/departments",
            data={
                "name": "Engineering",
                "code": "ENG2",
                "description": "Duplicate name",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.code == "ENG2")
            )
            dept = result.scalar_one_or_none()
            assert dept is None


@pytest.mark.asyncio
async def test_create_department_duplicate_code():
    await create_user(username="admin", password="adminpass123", role="super_admin")
    await create_department(name="Engineering", code="ENG")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            "/departments",
            data={
                "name": "Engineering 2",
                "code": "ENG",
                "description": "Duplicate code",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.name == "Engineering 2")
            )
            dept = result.scalar_one_or_none()
            assert dept is None


@pytest.mark.asyncio
async def test_edit_department_success():
    admin = await create_user(username="admin", password="adminpass123", role="super_admin")
    dept = await create_department(name="Engineering", code="ENG")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.get(
            f"/departments/{dept.id}/edit",
            follow_redirects=False,
        )
        assert response.status_code == 200

        response = await client.post(
            f"/departments/{dept.id}/edit",
            data={
                "name": "Engineering Updated",
                "code": "ENGU",
                "description": "Updated description",
                "head_id": str(admin.id),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/departments"

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.id == dept.id)
            )
            updated_dept = result.scalar_one_or_none()
            assert updated_dept is not None
            assert updated_dept.name == "Engineering Updated"
            assert updated_dept.code == "ENGU"
            assert updated_dept.description == "Updated description"
            assert updated_dept.head_id == admin.id


@pytest.mark.asyncio
async def test_edit_department_duplicate_name():
    await create_user(username="admin", password="adminpass123", role="super_admin")
    await create_department(name="Engineering", code="ENG")
    dept2 = await create_department(name="Marketing", code="MKT")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            f"/departments/{dept2.id}/edit",
            data={
                "name": "Engineering",
                "code": "MKT",
                "description": "Trying duplicate name",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.id == dept2.id)
            )
            unchanged_dept = result.scalar_one_or_none()
            assert unchanged_dept is not None
            assert unchanged_dept.name == "Marketing"


@pytest.mark.asyncio
async def test_delete_department_success():
    await create_user(username="admin", password="adminpass123", role="super_admin")
    dept = await create_department(name="Temporary", code="TMP")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            f"/departments/{dept.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/departments"

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.id == dept.id)
            )
            deleted_dept = result.scalar_one_or_none()
            assert deleted_dept is None


@pytest.mark.asyncio
async def test_delete_department_blocked_with_assigned_users():
    dept = await create_department(name="Engineering", code="ENG")
    await create_user(
        username="admin",
        password="adminpass123",
        role="super_admin",
        department_id=dept.id,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            f"/departments/{dept.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.id == dept.id)
            )
            dept_still_exists = result.scalar_one_or_none()
            assert dept_still_exists is not None
            assert dept_still_exists.name == "Engineering"


@pytest.mark.asyncio
async def test_delete_nonexistent_department():
    await create_user(username="admin", password="adminpass123", role="super_admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            "/departments/99999/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303


@pytest.mark.asyncio
async def test_rbac_developer_cannot_list_departments():
    await create_user(username="dev", password="devpass12345", role="developer")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "dev", "devpass12345")

        response = await client.get(
            "/departments",
            follow_redirects=False,
        )
        assert response.status_code in (302, 403)


@pytest.mark.asyncio
async def test_rbac_developer_cannot_create_department():
    await create_user(username="dev", password="devpass12345", role="developer")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "dev", "devpass12345")

        response = await client.post(
            "/departments",
            data={
                "name": "Unauthorized Dept",
                "code": "UNA",
                "description": "Should not be created",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code in (302, 403)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.code == "UNA")
            )
            dept = result.scalar_one_or_none()
            assert dept is None


@pytest.mark.asyncio
async def test_rbac_project_manager_cannot_manage_departments():
    await create_user(username="pm", password="pmpass12345", role="project_manager")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "pm", "pmpass12345")

        response = await client.get(
            "/departments",
            follow_redirects=False,
        )
        assert response.status_code in (302, 403)

        response = await client.post(
            "/departments",
            data={
                "name": "PM Dept",
                "code": "PMD",
                "description": "Should not be created",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code in (302, 403)


@pytest.mark.asyncio
async def test_rbac_viewer_cannot_manage_departments():
    await create_user(username="viewer", password="viewerpass123", role="viewer")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "viewer", "viewerpass123")

        response = await client.get(
            "/departments",
            follow_redirects=False,
        )
        assert response.status_code in (302, 403)


@pytest.mark.asyncio
async def test_rbac_developer_cannot_delete_department():
    dept = await create_department(name="Engineering", code="ENG")
    await create_user(username="dev", password="devpass12345", role="developer")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "dev", "devpass12345")

        response = await client.post(
            f"/departments/{dept.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code in (302, 403)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.id == dept.id)
            )
            dept_still_exists = result.scalar_one_or_none()
            assert dept_still_exists is not None


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_departments():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/departments",
            follow_redirects=False,
        )
        assert response.status_code in (302, 401)


@pytest.mark.asyncio
async def test_list_departments_page():
    await create_user(username="admin", password="adminpass123", role="super_admin")
    await create_department(name="Engineering", code="ENG")
    await create_department(name="Marketing", code="MKT")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.get(
            "/departments",
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Engineering" in response.text
        assert "Marketing" in response.text
        assert "ENG" in response.text
        assert "MKT" in response.text


@pytest.mark.asyncio
async def test_create_department_with_head():
    admin = await create_user(username="admin", password="adminpass123", role="super_admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            "/departments",
            data={
                "name": "Sales",
                "code": "SAL",
                "description": "Sales department",
                "head_id": str(admin.id),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.code == "SAL")
            )
            dept = result.scalar_one_or_none()
            assert dept is not None
            assert dept.head_id == admin.id


@pytest.mark.asyncio
async def test_create_department_empty_name_rejected():
    await create_user(username="admin", password="adminpass123", role="super_admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.post(
            "/departments",
            data={
                "name": "",
                "code": "EMP",
                "description": "Empty name",
                "head_id": "",
            },
            follow_redirects=False,
        )
        assert response.status_code in (303, 400, 422)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Department).where(Department.code == "EMP")
            )
            dept = result.scalar_one_or_none()
            assert dept is None


@pytest.mark.asyncio
async def test_edit_department_not_found():
    await create_user(username="admin", password="adminpass123", role="super_admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await login_user(client, "admin", "adminpass123")

        response = await client.get(
            "/departments/99999/edit",
            follow_redirects=False,
        )
        assert response.status_code == 303