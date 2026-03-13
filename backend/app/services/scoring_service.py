import logging
import re

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


COMPANY_SIZE_SCORES: dict[str, int] = {
    "500+": 30,
    "100-499": 25,
    "50-200": 18,
    "10-49": 10,
    "1-10": 5,
}

TITLE_PATTERNS: list[tuple[str, int]] = [
    (r"founder|ceo|owner|president", 30),
    (r"vp|vice president|director", 25),
    (r"manager|head of|lead", 15),
]


def calculate_score(
    title: str | None,
    company_size: str | None,
    industry: str | None,
    website: str | None,
    target_industry: str | None,
) -> int:
    score = 0

    # Company size
    size_key = (company_size or "").strip()
    score += COMPANY_SIZE_SCORES.get(size_key, 5)

    # Title seniority
    title_lower = (title or "").lower()
    matched = False
    for pattern, points in TITLE_PATTERNS:
        if re.search(pattern, title_lower):
            score += points
            matched = True
            break
    if not matched:
        score += 8

    # Industry fit
    if target_industry and industry:
        if industry.strip().lower() == target_industry.strip().lower():
            score += 20

    # Has website
    if website and website.strip():
        score += 10

    return min(score, 100)


async def generate_score_reason(
    score: int,
    title: str | None,
    company_size: str | None,
    industry: str | None,
) -> str:
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=40,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Write one sentence explaining why this lead scored {score}/100. "
                        f"Title: {title or 'unknown'}. "
                        f"Company size: {company_size or 'unknown'}. "
                        f"Industry: {industry or 'unknown'}. "
                        "Be specific and concise."
                    ),
                }
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Failed to generate score reason: %s", e)
        return f"Score of {score} based on title seniority, company size, and industry fit."


async def score_lead(lead, target_industry: str | None = None) -> tuple[int, str]:
    """Returns (score, score_reason)."""
    score = calculate_score(
        title=lead.title,
        company_size=lead.company_size,
        industry=lead.industry,
        website=lead.website,
        target_industry=target_industry,
    )
    reason = await generate_score_reason(
        score=score,
        title=lead.title,
        company_size=lead.company_size,
        industry=lead.industry,
    )
    logger.info("Scored lead %s: %d — %s", lead.email, score, reason)
    return score, reason
