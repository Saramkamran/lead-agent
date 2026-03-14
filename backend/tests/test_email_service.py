"""Tests for email_service.send_email.

Verifies SMTP payload shape, header correctness, Message-ID format, threading headers,
and error handling. All aiosmtplib.send calls are mocked — no real SMTP connections.
"""

import re
from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_service import send_email


# ── Success path ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_returns_message_id_on_success():
    """send_email returns a non-empty string on success."""
    with patch("aiosmtplib.send", new_callable=AsyncMock):
        result = await send_email(
            to_email="lead@example.com",
            to_name="Lead Name",
            subject="Hello",
            body_html="<p>Plain body</p>",
        )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_message_id_format():
    """Returned Message-ID must match <uuid@domain> format."""
    with patch("aiosmtplib.send", new_callable=AsyncMock):
        result = await send_email("t@t.com", "T", "S", "body")
    assert result.startswith("<")
    assert result.endswith(">")
    assert "@" in result


# ── Header verification ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_from_header_uses_smtp_settings(monkeypatch):
    """From header must use SMTP_FROM_EMAIL from settings."""
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "SMTP_FROM_EMAIL", "sender@company.com")
    monkeypatch.setattr(cfg.settings, "SMTP_FROM_NAME", "Sender Name")

    captured_msg = {}

    async def capture_send(msg, **kwargs):
        captured_msg["msg"] = msg

    with patch("aiosmtplib.send", side_effect=capture_send):
        await send_email("lead@example.com", "Lead", "Subject", "Body")

    msg = captured_msg["msg"]
    assert "sender@company.com" in msg["From"]


@pytest.mark.asyncio
async def test_to_header_correct():
    """To header must contain the recipient's email."""
    captured_msg = {}

    async def capture_send(msg, **kwargs):
        captured_msg["msg"] = msg

    with patch("aiosmtplib.send", side_effect=capture_send):
        await send_email("lead@example.com", "Lead Name", "Subject", "Body")

    assert "lead@example.com" in captured_msg["msg"]["To"]


@pytest.mark.asyncio
async def test_subject_header_correct():
    """Subject header must match the provided subject."""
    captured_msg = {}

    async def capture_send(msg, **kwargs):
        captured_msg["msg"] = msg

    with patch("aiosmtplib.send", side_effect=capture_send):
        await send_email("t@t.com", "T", "My Subject", "Body")

    assert captured_msg["msg"]["Subject"] == "My Subject"


# ── Threading headers ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_in_reply_to_set_when_replying():
    """In-Reply-To header must be set when reply_to_message_id is provided."""
    captured_msg = {}

    async def capture_send(msg, **kwargs):
        captured_msg["msg"] = msg

    with patch("aiosmtplib.send", side_effect=capture_send):
        await send_email(
            "t@t.com", "T", "S", "Body",
            reply_to_message_id="<original@domain.com>",
        )

    assert captured_msg["msg"]["In-Reply-To"] == "<original@domain.com>"


@pytest.mark.asyncio
async def test_references_header_built_correctly():
    """References header should contain the reply_to_message_id when thread_references given."""
    captured_msg = {}

    async def capture_send(msg, **kwargs):
        captured_msg["msg"] = msg

    with patch("aiosmtplib.send", side_effect=capture_send):
        await send_email(
            "t@t.com", "T", "S", "Body",
            reply_to_message_id="<msg1@domain.com>",
            thread_references="<msg0@domain.com> <msg1@domain.com>",
        )

    refs = captured_msg["msg"]["References"]
    assert "<msg1@domain.com>" in refs


@pytest.mark.asyncio
async def test_no_in_reply_to_when_not_replying():
    """In-Reply-To must NOT be set when no reply_to_message_id given."""
    captured_msg = {}

    async def capture_send(msg, **kwargs):
        captured_msg["msg"] = msg

    with patch("aiosmtplib.send", side_effect=capture_send):
        await send_email("t@t.com", "T", "S", "Body")

    assert captured_msg["msg"]["In-Reply-To"] is None


# ── Failure paths — must never raise ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_smtp_failure_returns_empty_string():
    """On SMTP exception, return '' and do NOT raise."""
    with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=Exception("Connection refused")):
        result = await send_email("t@t.com", "T", "S", "B")
    assert result == ""


@pytest.mark.asyncio
async def test_smtp_failure_does_not_raise():
    """Exceptions must be swallowed — background jobs must continue."""
    try:
        with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=RuntimeError("SMTP error")):
            await send_email("t@t.com", "T", "S", "B")
    except Exception:
        pytest.fail("send_email raised an exception — it must never propagate errors")


@pytest.mark.asyncio
async def test_timeout_error_returns_empty_string():
    """Timeout exceptions must also be swallowed."""
    with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=TimeoutError("Timeout")):
        result = await send_email("t@t.com", "T", "S", "B")
    assert result == ""
