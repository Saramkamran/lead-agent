"""Tests for reply_handler.handle_reply.

Verifies intent classification routing (positive/neutral/negative),
thread correlation via Message-ID / References headers, and unknown sender handling.
All DB, AI, and email calls are mocked.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.email_log import EmailLog
from app.models.lead import Lead

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _make_lead(db: AsyncSession, email: str, status: str = "contacted") -> Lead:
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


async def _make_outbound_log(db: AsyncSession, lead: Lead, message_id: str) -> EmailLog:
    log = EmailLog(
        id=str(uuid.uuid4()),
        lead_id=lead.id,
        direction="outbound",
        message_id=message_id,
        subject="Cold email",
        body="Hello",
    )
    db.add(log)
    await db.commit()
    return log


# ── Negative intent ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_negative_intent_sets_not_interested(db):
    lead = await _make_lead(db, "negative@example.com")
    await _make_outbound_log(db, lead, "<outbound-001@domain.com>")

    reply_data = {
        "from_email": "negative@example.com",
        "subject": "Re: Cold email",
        "body": "Not interested.",
        "message_id": "<reply-001@domain.com>",
        "in_reply_to": "<outbound-001@domain.com>",
        "references": "<outbound-001@domain.com>",
    }

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    with patch("app.services.reply_handler.AsyncSessionLocal", return_value=factory()), \
         patch("app.services.reply_handler.classify_intent", new_callable=AsyncMock, return_value="negative"):
        from app.services.reply_handler import handle_reply
        await handle_reply(reply_data)

    await db.refresh(lead)
    assert lead.status == "not_interested"


# ── Positive intent ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_positive_creates_conversation_and_sets_replied(db):
    lead = await _make_lead(db, "positive@example.com")
    await _make_outbound_log(db, lead, "<outbound-002@domain.com>")

    reply_data = {
        "from_email": "positive@example.com",
        "subject": "Re: Cold email",
        "body": "Yes, I am interested!",
        "message_id": "<reply-002@domain.com>",
        "in_reply_to": "<outbound-002@domain.com>",
        "references": "<outbound-002@domain.com>",
    }

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    with patch("app.services.reply_handler.AsyncSessionLocal", return_value=factory()), \
         patch("app.services.reply_handler.classify_intent", new_callable=AsyncMock, return_value="positive"), \
         patch("app.services.reply_handler.generate_reply", new_callable=AsyncMock, return_value="Great to hear!"), \
         patch("app.services.reply_handler.send_email", new_callable=AsyncMock, return_value="<ai-reply@domain.com>"):
        from app.services.reply_handler import handle_reply
        await handle_reply(reply_data)

    await db.refresh(lead)
    assert lead.status == "replied"


# ── Neutral intent ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_neutral_also_replies(db):
    lead = await _make_lead(db, "neutral@example.com")
    await _make_outbound_log(db, lead, "<outbound-003@domain.com>")

    reply_data = {
        "from_email": "neutral@example.com",
        "subject": "Re: Cold email",
        "body": "Maybe, send me more info.",
        "message_id": "<reply-003@domain.com>",
        "in_reply_to": "<outbound-003@domain.com>",
        "references": "<outbound-003@domain.com>",
    }

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    with patch("app.services.reply_handler.AsyncSessionLocal", return_value=factory()), \
         patch("app.services.reply_handler.classify_intent", new_callable=AsyncMock, return_value="neutral"), \
         patch("app.services.reply_handler.generate_reply", new_callable=AsyncMock, return_value="Sure, here's more info."), \
         patch("app.services.reply_handler.send_email", new_callable=AsyncMock, return_value="<ai-neutral@domain.com>"):
        from app.services.reply_handler import handle_reply
        await handle_reply(reply_data)

    await db.refresh(lead)
    assert lead.status == "replied"


# ── No matching thread ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_matching_thread_returns_silently(db):
    """If References/In-Reply-To don't match any outbound email_log, do nothing."""
    lead = await _make_lead(db, "nomatch@example.com")

    reply_data = {
        "from_email": "nomatch@example.com",
        "subject": "Random email",
        "body": "Hello",
        "message_id": "<random@domain.com>",
        "in_reply_to": "<unknown-id@domain.com>",
        "references": "<unknown-id@domain.com>",
    }

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    classify_mock = AsyncMock()

    with patch("app.services.reply_handler.AsyncSessionLocal", return_value=factory()), \
         patch("app.services.reply_handler.classify_intent", classify_mock):
        from app.services.reply_handler import handle_reply
        await handle_reply(reply_data)

    # classify_intent should NOT have been called — we returned early
    classify_mock.assert_not_called()
    # Lead status unchanged
    await db.refresh(lead)
    assert lead.status == "contacted"


# ── Thread correlation via References ────────────────────────────────────────

@pytest.mark.asyncio
async def test_thread_correlation_via_references_header(db):
    """Handle reply should match via the References header (space-split message IDs)."""
    lead = await _make_lead(db, "refs@example.com")
    await _make_outbound_log(db, lead, "<first-email@domain.com>")

    reply_data = {
        "from_email": "refs@example.com",
        "subject": "Re: Cold email",
        "body": "Not interested at all.",
        "message_id": "<reply-refs@domain.com>",
        "in_reply_to": "",
        # References contains multiple IDs including our outbound one
        "references": "<first-email@domain.com> <some-other@domain.com>",
    }

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    with patch("app.services.reply_handler.AsyncSessionLocal", return_value=factory()), \
         patch("app.services.reply_handler.classify_intent", new_callable=AsyncMock, return_value="negative"):
        from app.services.reply_handler import handle_reply
        await handle_reply(reply_data)

    await db.refresh(lead)
    assert lead.status == "not_interested"
