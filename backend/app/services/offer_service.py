import logging

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def generate_offer(lead: Lead, db: AsyncSession) -> str:
    """
    Generate a 1-sentence value proposition for the lead.
    Caches by industry + title + company_size — reuses existing offer if found.
    """
    # Cache check: find another lead with same industry+title+company_size that has an offer
    if lead.industry or lead.title or lead.company_size:
        result = await db.execute(
            select(Lead.custom_offer).where(
                Lead.industry == lead.industry,
                Lead.title == lead.title,
                Lead.company_size == lead.company_size,
                Lead.custom_offer.isnot(None),
                Lead.id != lead.id,
            ).limit(1)
        )
        cached = result.scalar_one_or_none()
        if cached:
            logger.info("Cache hit for offer — reusing for lead %s", lead.email)
            return cached

    # Generate via OpenAI
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=60,
            messages=[
                {
                    "role": "user",
                    "content": (
                        'Write one sentence. Format: "We help [role] at [company type] to [specific outcome]."\n'
                        f"Role: {lead.title or 'professional'} | "
                        f"Industry: {lead.industry or 'general'} | "
                        f"Size: {lead.company_size or 'any size'}\n"
                        "Max 25 words. No filler words. Be specific."
                    ),
                }
            ],
        )
        offer = response.choices[0].message.content.strip()
        logger.info("Generated offer for lead %s", lead.email)
        return offer
    except Exception as e:
        logger.error("Failed to generate offer for lead %s: %s", lead.email, e)
        return f"We help {lead.title or 'professionals'} at {lead.industry or 'companies'} to grow their business."
