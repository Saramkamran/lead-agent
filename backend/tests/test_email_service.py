"""Tests for email_service.send_email.

Verifies Brevo API payload shape, auth header format, and error handling.
All httpx calls are mocked — no real network requests are made.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.email_service import send_email


def _mock_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _make_mock_client(response: MagicMock):
    """Return a mock httpx.AsyncClient context manager that returns response."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=response)
    return mock_client


# ── Success path ───────────────────────────────────────────────────────────────

async def test_returns_message_id_on_success():
    mock_resp = _mock_response(201, {"messageId": "brevo-msg-001"})
    with patch("app.services.email_service.httpx.AsyncClient", return_value=_make_mock_client(mock_resp)):
        result = await send_email(
            to_email="lead@example.com",
            to_name="Lead Name",
            subject="Hello from us",
            body="Plain text body here.",
            from_email="sender@company.com",
            from_name="Sender Name",
        )
    assert result == "brevo-msg-001"


async def test_also_accepts_200_status():
    mock_resp = _mock_response(200, {"messageId": "brevo-msg-200"})
    with patch("app.services.email_service.httpx.AsyncClient", return_value=_make_mock_client(mock_resp)):
        result = await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")
    assert result == "brevo-msg-200"


# ── Header verification ────────────────────────────────────────────────────────

async def test_uses_api_key_header_not_bearer():
    """Brevo requires the 'api-key' header; Authorization: Bearer must NOT be sent."""
    captured: dict = {}
    mock_resp = _mock_response(201, {"messageId": "id-abc"})

    async def capture_post(url, headers=None, json=None, **kwargs):
        captured.update(headers or {})
        return mock_resp

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = capture_post

    with patch("app.services.email_service.httpx.AsyncClient", return_value=mock_client):
        await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")

    assert "api-key" in captured
    assert "Authorization" not in captured


# ── Payload shape ──────────────────────────────────────────────────────────────

async def test_payload_contains_required_fields():
    """Payload must have sender, to, subject, textContent (not htmlContent)."""
    captured: dict = {}
    mock_resp = _mock_response(201, {"messageId": "x"})

    async def capture_post(url, headers=None, json=None, **kwargs):
        captured.update(json or {})
        return mock_resp

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = capture_post

    with patch("app.services.email_service.httpx.AsyncClient", return_value=mock_client):
        await send_email(
            to_email="lead@example.com",
            to_name="Lead Name",
            subject="Test Subject",
            body="Test body text",
            from_email="sender@company.com",
            from_name="Sender",
        )

    assert "sender" in captured
    assert captured["sender"]["email"] == "sender@company.com"
    assert captured["sender"]["name"] == "Sender"

    assert "to" in captured
    assert captured["to"][0]["email"] == "lead@example.com"
    assert captured["to"][0]["name"] == "Lead Name"

    assert captured["subject"] == "Test Subject"
    assert "textContent" in captured
    assert captured["textContent"] == "Test body text"
    assert "htmlContent" not in captured


async def test_posts_to_brevo_smtp_url():
    captured_url: list = []
    mock_resp = _mock_response(201, {"messageId": "ok"})

    async def capture_post(url, **kwargs):
        captured_url.append(url)
        return mock_resp

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = capture_post

    with patch("app.services.email_service.httpx.AsyncClient", return_value=mock_client):
        await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")

    assert captured_url[0] == "https://api.brevo.com/v3/smtp/email"


# ── Failure paths — must never raise ──────────────────────────────────────────

async def test_api_error_returns_empty_string():
    """On non-2xx response, return '' and do NOT raise."""
    mock_resp = _mock_response(400, {"message": "Invalid API key"})
    with patch("app.services.email_service.httpx.AsyncClient", return_value=_make_mock_client(mock_resp)):
        result = await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")
    assert result == ""


async def test_network_error_returns_empty_string():
    """On network exception, return '' and do NOT propagate the exception."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(
        side_effect=Exception("Connection refused")
    )
    with patch("app.services.email_service.httpx.AsyncClient", return_value=mock_client):
        result = await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")
    assert result == ""


async def test_timeout_error_returns_empty_string():
    """Timeout exceptions must also be swallowed."""
    import httpx
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(
        side_effect=httpx.TimeoutException("Timeout")
    )
    with patch("app.services.email_service.httpx.AsyncClient", return_value=mock_client):
        result = await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")
    assert result == ""


async def test_500_server_error_returns_empty_string():
    mock_resp = _mock_response(500, {"message": "Internal server error"})
    with patch("app.services.email_service.httpx.AsyncClient", return_value=_make_mock_client(mock_resp)):
        result = await send_email("t@t.com", "T", "S", "B", "f@f.com", "F")
    assert result == ""
