"""Tests for message_service.generate_messages.

Verifies:
- Three messages are created on first call (cold_email, followup_1, followup_2)
- OpenAI is NOT called if messages already exist for the lead (caching)
- Calling generate_messages twice for same lead only hits OpenAI once
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.message import Message
from app.services.message_service import generate_messages

FAKE_OPENAI_RESPONSE = json.dumps({
    "cold_email": {
        "subject": "Improve your SaaS conversion",
        "body": "Hi Alice, reaching out about your team's conversion challenges.",
    },
    "followup_1": {
        "subject": "Re: Improve your SaaS conversion",
        "body": "Just following up — did you get a chance to look? Book a slot: cal.ly/test",
    },
    "followup_2": {
        "subject": "Re: Improve your SaaS conversion",
        "body": "Last nudge — happy to connect at cal.ly/test",
    },
})


def _make_lead() -> Lead:
    return Lead(
        id=str(uuid.uuid4()),
        email=f"lead-{uuid.uuid4()}@example.com",
        first_name="Alice",
        last_name="Smith",
        company="Acme Corp",
        title="VP of Sales",
        industry="SaaS",
        company_size="100-499",
        website="acme.com",
        custom_offer="We help VP-level execs at SaaS companies to increase ARR.",
    )


async def test_generate_messages_creates_three_messages(db_session: AsyncSession):
    lead = _make_lead()
    db_session.add(lead)
    await db_session.flush()

    mock_response = AsyncMock()
    mock_response.choices[0].message.content = FAKE_OPENAI_RESPONSE

    with patch("app.services.message_service._get_client") as mock_get_client:
        mock_get_client.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        messages = await generate_messages(
            lead=lead,
            sender_name="Jane Doe",
            sender_company="My Company",
            calendly_link="cal.ly/test",
            db=db_session,
        )

    assert len(messages) == 3
    types = {m.type for m in messages}
    assert types == {"cold_email", "followup_1", "followup_2"}
    for m in messages:
        assert m.status == "pending"
        assert m.subject
        assert m.body


async def test_generate_messages_caches_existing(db_session: AsyncSession):
    """OpenAI must NOT be called if messages already exist for the lead."""
    lead = _make_lead()
    db_session.add(lead)
    await db_session.flush()

    existing = Message(
        id=str(uuid.uuid4()),
        lead_id=lead.id,
        type="cold_email",
        subject="Already generated",
        body="Existing body",
        status="pending",
    )
    db_session.add(existing)
    await db_session.flush()

    with patch("app.services.message_service._get_client") as mock_get_client:
        returned = await generate_messages(
            lead=lead,
            sender_name="Jane",
            sender_company="Corp",
            calendly_link="cal.ly/x",
            db=db_session,
        )
        mock_get_client.assert_not_called()

    assert len(returned) >= 1


async def test_generate_messages_openai_called_exactly_once_per_lead(db_session: AsyncSession):
    """Two calls to generate_messages for the same lead → exactly 1 OpenAI call."""
    lead = _make_lead()
    db_session.add(lead)
    await db_session.flush()

    mock_response = AsyncMock()
    mock_response.choices[0].message.content = FAKE_OPENAI_RESPONSE

    with patch("app.services.message_service._get_client") as mock_get_client:
        create_mock = AsyncMock(return_value=mock_response)
        mock_get_client.return_value.chat.completions.create = create_mock

        # First call — should hit OpenAI
        await generate_messages(lead, "Jane", "Corp", "cal.ly/x", db_session)
        await db_session.commit()

        first_call_count = create_mock.call_count
        assert first_call_count == 1

        # Second call — should return cached, no new OpenAI call
        await generate_messages(lead, "Jane", "Corp", "cal.ly/x", db_session)

    assert create_mock.call_count == 1  # unchanged


async def test_generate_messages_stores_correct_types(db_session: AsyncSession):
    lead = _make_lead()
    db_session.add(lead)
    await db_session.flush()

    mock_response = AsyncMock()
    mock_response.choices[0].message.content = FAKE_OPENAI_RESPONSE

    with patch("app.services.message_service._get_client") as mock_get_client:
        mock_get_client.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        messages = await generate_messages(lead, "J", "C", "cal.ly/x", db_session)

    cold = next(m for m in messages if m.type == "cold_email")
    f1 = next(m for m in messages if m.type == "followup_1")
    f2 = next(m for m in messages if m.type == "followup_2")

    assert cold.subject == "Improve your SaaS conversion"
    assert "Re:" in f1.subject
    assert "Re:" in f2.subject
    assert cold.lead_id == lead.id
