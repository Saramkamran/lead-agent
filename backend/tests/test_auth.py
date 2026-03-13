"""Tests for /auth/register and /auth/login endpoints."""

from httpx import AsyncClient


async def test_register_success(client: AsyncClient):
    resp = await client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "user@example.com"
    assert "id" in data


async def test_register_duplicate_email(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "password123"},
    )
    resp = await client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "different"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "EMAIL_EXISTS"


async def test_login_success(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "login@example.com", "password": "mypassword"},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "mypassword"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "wrong@example.com", "password": "correct"},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": "wrong@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email(client: AsyncClient):
    resp = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "any"},
    )
    assert resp.status_code == 401


async def test_protected_route_requires_auth(client: AsyncClient):
    resp = await client.get("/leads")
    # HTTPBearer returns 403 when no header is present, 401 for invalid tokens
    assert resp.status_code in (401, 403)


async def test_protected_route_with_valid_token(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/leads", headers=auth_headers)
    assert resp.status_code == 200
