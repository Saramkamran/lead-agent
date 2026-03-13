import json
import logging

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.lead import Lead
from app.models.message import Message

logger = logging.getLogger(__name__)

_client = None

SYSTEM_PROMPT = (
    "You write cold outreach emails. Be direct, human, and brief.\n"
    "Never start with \"I hope this finds you well.\" No fluff.\n"
    "Lead with a specific pain point relevant to their industry and role.\n"
    "Return valid JSON only — no markdown, no explanation outside the JSON."
)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def generate_messages(
    lead: Lead,
    sender_name: str,
    sender_company: str,
    calendly_link: str,
    db: AsyncSession,
) -> list[Message]:
    """
    Generate cold_email, followup_1, followup_2 for a lead.
    Never regenerates if messages already exist for this lead.
    Returns list of Message objects (already added to session).
    """
    # Cache check — never regenerate
    existing = await db.execute(
        select(Message).where(Message.lead_id == lead.id).limit(1)
    )
    if existing.scalar_one_or_none():
        logger.info("Messages already exist for lead %s — skipping generation", lead.email)
        all_msgs = await db.execute(select(Message).where(Message.lead_id == lead.id))
        return list(all_msgs.scalars().all())

    user_prompt = (
        f"Generate 3 outreach emails for this lead.\n\n"
        f"Lead: {lead.first_name or ''} {lead.last_name or ''}, "
        f"{lead.title or 'professional'} at {lead.company or 'their company'} "
        f"({lead.industry or 'unknown industry'}, {lead.company_size or 'unknown size'})\n"
        f"Offer: {lead.custom_offer or 'We can help your business grow.'}\n"
        f"Sender: {sender_name}, {sender_company}\n"
        f"Calendly booking link: {calendly_link}\n\n"
        "Return this exact JSON structure:\n"
        "{\n"
        '  "cold_email": { "subject": "...", "body": "..." },\n'
        '  "followup_1": { "subject": "Re: [original subject]", "body": "..." },\n'
        '  "followup_2": { "subject": "Re: [original subject]", "body": "..." }\n'
        "}\n\n"
        "cold_email body: max 100 words.\n"
        "followup_1 body: max 60 words. Reference the previous email briefly.\n"
        "followup_2 body: max 50 words. Final nudge, low pressure.\n"
        "Include the Calendly link only in followup_1 and followup_2."
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON parse error for lead %s: %s", lead.email, e)
        raise
    except Exception as e:
        logger.error("OpenAI error generating messages for lead %s: %s", lead.email, e)
        raise

    messages = []
    for msg_type in ("cold_email", "followup_1", "followup_2"):
        entry = data.get(msg_type, {})
        msg = Message(
            lead_id=lead.id,
            type=msg_type,
            subject=entry.get("subject", ""),
            body=entry.get("body", ""),
            status="pending",
        )
        db.add(msg)
        messages.append(msg)

    await db.flush()
    logger.info("Generated 3 messages for lead %s", lead.email)
    return messages
