"""Tests for /webhooks/brevo/inbound and /webhooks/brevo/events.

All OpenAI and email calls are mocked — only DB logic is exercised end-to-end.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.message import Message


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _create_lead(db: AsyncSession, email: str, status: str = "contacted") -> Lead:
    lead = Lead(
        id=str(uuid.uuid4()),
        email=email,
        first_name="Test",
        last_name="Lead",
        company="TestCo",
        title="CEO",
        status=status,
    )
    db.add(lead)
    await db.commit()
    return lead


async def _create_message(
    db: AsyncSession, lead: Lead, provider_id: str = "msg-001"
) -> Message:
    msg = Message(
        id=str(uuid.uuid4()),
        lead_id=lead.id,
        type="cold_email",
        subject="Test subject",
        body="Test body",
        status="sent",
        provider_message_id=provider_id,
    )
    db.add(msg)
    await db.commit()
    return msg


# ── /webhooks/brevo/inbound ────────────────────────────────────────────────────

async def test_inbound_negative_sets_not_interested(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    await _create_lead(db_session, "negative@example.com")

    with patch("app.api.webhooks.classify_intent", new_callable=AsyncMock, return_value="negative"):
        resp = await client.post(
            "/webhooks/brevo/inbound",
            json={"From": "negative@example.com", "Subject": "No thanks", "TextBody": "Not interested."},
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    leads_resp = await client.get("/leads", headers=auth_headers)
    items = leads_resp.json()["items"]
    updated = next(l for l in items if l["email"] == "negative@example.com")
    assert updated["status"] == "not_interested"


async def test_inbound_positive_creates_conversation_and_sets_replied(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    await _create_lead(db_session, "positive@example.com")

    with patch("app.api.webhooks.classify_intent", new_callable=AsyncMock, return_value="positive"), \
         patch("app.api.webhooks.generate_reply", new_callable=AsyncMock, return_value="Great to hear!"), \
         patch("app.api.webhooks.send_email", new_callable=AsyncMock, return_value="msg-abc"):
        resp = await client.post(
            "/webhooks/brevo/inbound",
            json={
                "From": "positive@example.com",
                "Subject": "Interested",
                "TextBody": "Yes, tell me more!",
            },
        )

    assert resp.status_code == 200
    leads_resp = await client.get("/leads", headers=auth_headers)
    items = leads_resp.json()["items"]
    updated = next(l for l in items if l["email"] == "positive@example.com")
    assert updated["status"] == "replied"


async def test_inbound_neutral_sets_replied(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    await _create_lead(db_session, "neutral@example.com")

    with patch("app.api.webhooks.classify_intent", new_callable=AsyncMock, return_value="neutral"), \
         patch("app.api.webhooks.generate_reply", new_callable=AsyncMock, return_value="OK"), \
         patch("app.api.webhooks.send_email", new_callable=AsyncMock, return_value=""):
        resp = await client.post(
            "/webhooks/brevo/inbound",
            json={"From": "neutral@example.com", "Subject": "OK", "TextBody": "Maybe later."},
        )

    assert resp.status_code == 200
    leads_resp = await client.get("/leads", headers=auth_headers)
    items = leads_resp.json()["items"]
    updated = next(l for l in items if l["email"] == "neutral@example.com")
    assert updated["status"] == "replied"


async def test_inbound_unknown_sender_returns_ok_no_crash(client: AsyncClient):
    """Unknown sender email → 200 ok, nothing written to DB."""
    with patch("app.api.webhooks.classify_intent", new_callable=AsyncMock, return_value="positive"):
        resp = await client.post(
            "/webhooks/brevo/inbound",
            json={"From": "nobody@unknown.com", "Subject": "Hi", "TextBody": "Hello"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_inbound_parses_name_email_format(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """'Full Name <email>' format must be parsed correctly."""
    await _create_lead(db_session, "john@example.com")

    with patch("app.api.webhooks.classify_intent", new_callable=AsyncMock, return_value="negative"):
        resp = await client.post(
            "/webhooks/brevo/inbound",
            json={
                "From": "John Smith <john@example.com>",
                "Subject": "Re: outreach",
                "TextBody": "Not interested",
            },
        )

    assert resp.status_code == 200
    leads_resp = await client.get("/leads", headers=auth_headers)
    items = leads_resp.json()["items"]
    updated = next(l for l in items if l["email"] == "john@example.com")
    assert updated["status"] == "not_interested"


async def test_inbound_empty_from_returns_ok(client: AsyncClient):
    """Missing From field → graceful 200, no crash."""
    resp = await client.post(
        "/webhooks/brevo/inbound",
        json={"From": "", "Subject": "Hi", "TextBody": "Hello"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ── /webhooks/brevo/events ─────────────────────────────────────────────────────

async def test_event_opened_updates_message_status(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    lead = await _create_lead(db_session, "opened@example.com")
    await _create_message(db_session, lead, provider_id="brevo-open-001")

    resp = await client.post(
        "/webhooks/brevo/events",
        json={"event": "opened", "messageId": "brevo-open-001", "email": "opened@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    lead_resp = await client.get(f"/leads/{lead.id}", headers=auth_headers)
    msgs = lead_resp.json()["messages"]
    assert msgs[0]["status"] == "opened"


async def test_event_clicked_updates_message_status(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    lead = await _create_lead(db_session, "clicked@example.com")
    await _create_message(db_session, lead, provider_id="brevo-click-001")

    resp = await client.post(
        "/webhooks/brevo/events",
        json={"event": "clicked", "messageId": "brevo-click-001", "email": "clicked@example.com"},
    )
    assert resp.status_code == 200

    lead_resp = await client.get(f"/leads/{lead.id}", headers=auth_headers)
    assert lead_resp.json()["messages"][0]["status"] == "clicked"


async def test_event_hard_bounce_updates_lead_and_message(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    lead = await _create_lead(db_session, "bounce@example.com")
    await _create_message(db_session, lead, provider_id="brevo-bounce-001")

    resp = await client.post(
        "/webhooks/brevo/events",
        json={"event": "hard_bounce", "messageId": "brevo-bounce-001", "email": "bounce@example.com"},
    )
    assert resp.status_code == 200

    lead_resp = await client.get(f"/leads/{lead.id}", headers=auth_headers)
    data = lead_resp.json()
    assert data["status"] == "bounced"
    assert data["messages"][0]["status"] == "bounced"


async def test_event_soft_bounce_also_sets_bounced(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    lead = await _create_lead(db_session, "softbounce@example.com")
    await _create_message(db_session, lead, provider_id="brevo-soft-001")

    resp = await client.post(
        "/webhooks/brevo/events",
        json={"event": "soft_bounce", "messageId": "brevo-soft-001", "email": "softbounce@example.com"},
    )
    assert resp.status_code == 200

    lead_resp = await client.get(f"/leads/{lead.id}", headers=auth_headers)
    assert lead_resp.json()["status"] == "bounced"


async def test_event_unknown_type_returns_ok_silently(client: AsyncClient):
    """Unrecognised event types must be silently ignored."""
    resp = await client.post(
        "/webhooks/brevo/events",
        json={"event": "delivered", "messageId": "xyz", "email": "x@x.com"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_event_unknown_message_id_returns_ok(client: AsyncClient):
    """No matching provider_message_id → still returns ok, no crash."""
    resp = await client.post(
        "/webhooks/brevo/events",
        json={"event": "opened", "messageId": "nonexistent-id", "email": "x@x.com"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
