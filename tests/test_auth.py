import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app
from database import engine, Base
from dependencies import SESSION_COOKIE_NAME, FLASH_COOKIE_NAME


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def register_user(client: AsyncClient, username: str = "testuser", password: str = "password123", confirm_password: str = "password123"):
    return await client.post(
        "/auth/register",
        data={
            "username": username,
            "password": password,
            "confirm_password": confirm_password,
        },
        follow_redirects=False,
    )


async def login_user(client: AsyncClient, username: str = "testuser", password: str = "password123"):
    return await client.post(
        "/auth/login",
        data={
            "username": username,
            "password": password,
        },
        follow_redirects=False,
    )


class TestRegistration:
    @pytest.mark.asyncio
    async def test_register_page_loads(self, client: AsyncClient):
        response = await client.get("/auth/register")
        assert response.status_code == 200
        assert "Create your account" in response.text

    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        response = await register_user(client)
        assert response.status_code == 302
        assert response.headers.get("location") == "/dashboard"

        cookies = response.cookies
        assert SESSION_COOKIE_NAME in cookies

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, client: AsyncClient):
        response1 = await register_user(client, username="dupuser")
        assert response1.status_code == 302

        response2 = await register_user(client, username="dupuser")
        assert response2.status_code == 400
        assert "already taken" in response2.text

    @pytest.mark.asyncio
    async def test_register_password_mismatch(self, client: AsyncClient):
        response = await register_user(
            client,
            username="mismatchuser",
            password="password123",
            confirm_password="differentpassword",
        )
        assert response.status_code == 400
        assert "Passwords do not match" in response.text

    @pytest.mark.asyncio
    async def test_register_short_username(self, client: AsyncClient):
        response = await register_user(client, username="ab")
        assert response.status_code == 400
        assert "at least 3 characters" in response.text

    @pytest.mark.asyncio
    async def test_register_short_password(self, client: AsyncClient):
        response = await register_user(client, username="validuser", password="short", confirm_password="short")
        assert response.status_code == 400
        assert "at least 8 characters" in response.text

    @pytest.mark.asyncio
    async def test_register_non_alphanumeric_username(self, client: AsyncClient):
        response = await register_user(client, username="bad user!")
        assert response.status_code == 400
        assert "letters and numbers" in response.text

    @pytest.mark.asyncio
    async def test_register_redirects_if_logged_in(self, client: AsyncClient):
        reg_response = await register_user(client, username="loggedin")
        assert reg_response.status_code == 302
        session_cookie = reg_response.cookies.get(SESSION_COOKIE_NAME)

        client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
        get_response = await client.get("/auth/register", follow_redirects=False)
        assert get_response.status_code == 302
        assert get_response.headers.get("location") == "/dashboard"


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_page_loads(self, client: AsyncClient):
        response = await client.get("/auth/login")
        assert response.status_code == 200
        assert "Sign in to ProjectForge" in response.text

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        await register_user(client, username="loginuser", password="password123")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as fresh_client:
            response = await login_user(fresh_client, username="loginuser", password="password123")
            assert response.status_code == 302
            assert response.headers.get("location") == "/dashboard"
            assert SESSION_COOKIE_NAME in response.cookies

    @pytest.mark.asyncio
    async def test_login_invalid_username(self, client: AsyncClient):
        response = await login_user(client, username="nonexistent", password="password123")
        assert response.status_code == 400
        assert "Invalid username or password" in response.text

    @pytest.mark.asyncio
    async def test_login_invalid_password(self, client: AsyncClient):
        await register_user(client, username="wrongpwuser", password="password123")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as fresh_client:
            response = await login_user(fresh_client, username="wrongpwuser", password="wrongpassword")
            assert response.status_code == 400
            assert "Invalid username or password" in response.text

    @pytest.mark.asyncio
    async def test_login_redirects_if_logged_in(self, client: AsyncClient):
        reg_response = await register_user(client, username="alreadyin")
        session_cookie = reg_response.cookies.get(SESSION_COOKIE_NAME)

        client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
        get_response = await client.get("/auth/login", follow_redirects=False)
        assert get_response.status_code == 302
        assert get_response.headers.get("location") == "/dashboard"


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_clears_session(self, client: AsyncClient):
        reg_response = await register_user(client, username="logoutuser", password="password123")
        assert reg_response.status_code == 302
        session_cookie = reg_response.cookies.get(SESSION_COOKIE_NAME)
        assert session_cookie is not None

        client.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        logout_response = await client.post("/auth/logout", follow_redirects=False)
        assert logout_response.status_code == 302
        assert logout_response.headers.get("location") == "/"

        session_header = logout_response.headers.get("set-cookie", "")
        assert SESSION_COOKIE_NAME in session_header


class TestSessionCookie:
    @pytest.mark.asyncio
    async def test_session_cookie_is_set_on_register(self, client: AsyncClient):
        response = await register_user(client, username="cookieuser")
        assert response.status_code == 302
        assert SESSION_COOKIE_NAME in response.cookies

    @pytest.mark.asyncio
    async def test_session_cookie_is_set_on_login(self, client: AsyncClient):
        await register_user(client, username="cookielogin", password="password123")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as fresh_client:
            response = await login_user(fresh_client, username="cookielogin", password="password123")
            assert response.status_code == 302
            assert SESSION_COOKIE_NAME in response.cookies

    @pytest.mark.asyncio
    async def test_invalid_session_cookie_rejected(self, client: AsyncClient):
        client.cookies.set(SESSION_COOKIE_NAME, "invalid-garbage-cookie-value")
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_session_cookie_grants_dashboard_access(self, client: AsyncClient):
        reg_response = await register_user(client, username="dashuser")
        session_cookie = reg_response.cookies.get(SESSION_COOKIE_NAME)

        client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
        dashboard_response = await client.get("/dashboard", follow_redirects=False)
        assert dashboard_response.status_code == 200
        assert "Dashboard" in dashboard_response.text

    @pytest.mark.asyncio
    async def test_session_decode_and_create(self):
        from dependencies import create_session, decode_session

        user_id = 42
        token = create_session(user_id)
        assert isinstance(token, str)
        assert len(token) > 0

        decoded_id = decode_session(token)
        assert decoded_id == user_id

    @pytest.mark.asyncio
    async def test_session_decode_expired(self):
        from dependencies import decode_session, serializer

        token = serializer.dumps({"user_id": 99})
        result = decode_session(token, max_age=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_session_decode_bad_signature(self):
        from dependencies import decode_session

        result = decode_session("totally.invalid.token")
        assert result is None