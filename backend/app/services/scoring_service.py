import json
import logging
import re

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Rule-based fallback (used when Claude is unavailable) ─────────────────────

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


def _rule_based_score(
    title: str | None,
    company_size: str | None,
    industry: str | None,
    website: str | None,
    target_industry: str | None,
) -> int:
    score = 0
    size_key = (company_size or "").strip()
    score += COMPANY_SIZE_SCORES.get(size_key, 5)
    title_lower = (title or "").lower()
    matched = False
    for pattern, points in TITLE_PATTERNS:
        if re.search(pattern, title_lower):
            score += points
            matched = True
            break
    if not matched:
        score += 8
    if target_industry and industry:
        if industry.strip().lower() == target_industry.strip().lower():
            score += 20
    if website and website.strip():
        score += 10
    return min(score, 100)


# ── Claude-powered scoring ────────────────────────────────────────────────────

async def _score_with_claude(lead, scan, target_industry: str | None) -> tuple[int, str]:
    """
    Use Claude to score a lead using all available intelligence.
    Returns (score, reason). Raises on error so caller can fall back.
    """
    import anthropic

    # Build website intelligence section
    website_intel = ""
    if scan:
        pain_points = []
        growth_signals = []
        trust_signals = []
        try:
            pain_points = json.loads(scan.pain_points or "[]")
        except Exception:
            pass
        try:
            growth_signals = json.loads(scan.growth_signals or "[]")
        except Exception:
            pass
        try:
            trust_signals = json.loads(scan.trust_signals or "[]")
        except Exception:
            pass

        social_platforms = []
        try:
            social_dict = json.loads(scan.social_links or "{}")
            social_platforms = list(social_dict.keys())
        except Exception:
            pass

        website_intel = f"""
Website intelligence:
- Business type: {scan.business_type or "unknown"}
- Services: {scan.services_list or "unknown"}
- Has booking system: {scan.has_booking_system}
- Has pricing page: {scan.has_pricing_page}
- Has contact form: {scan.has_contact_form}
- CTA strength: {scan.cta_strength or "none"}
- Design quality: {scan.design_quality or "unknown"}
- Pain points identified: {", ".join(pain_points) if pain_points else "none found"}
- Growth signals: {", ".join(growth_signals) if growth_signals else "none found"}
- Trust signals: {", ".join(trust_signals) if trust_signals else "none found"}
- Social media presence: {", ".join(social_platforms) if social_platforms else "none detected"}
- Urgency level: {scan.urgency_level or "unknown"}
- Best connection angle: {scan.connection_angle or "none"}"""
    else:
        website_intel = "\nWebsite intelligence: not available (scan failed or no website)"

    prompt = f"""You are a B2B lead scoring expert for a company that builds lead capture and booking automation systems for local and small-to-medium businesses.

Score this prospect from 0 to 100.

LEAD DATA:
- Contact title: {lead.title or "unknown"}
- Company: {lead.company or "unknown"}
- Company size: {lead.company_size or "unknown"}
- Industry: {lead.industry or "unknown"}
- Has website: {"yes" if lead.website else "no"}
- Target industry for this campaign: {target_industry or "any"}
{website_intel}

SCORING CRITERIA:
90-100: Perfect fit — clear decision maker (CEO/founder/owner), has a website with no booking system, active business, in target industry, high urgency
70-89: Strong fit — likely decision maker, clear pain points we can solve, good industry match
50-69: Medium fit — some opportunity but lower priority (manager-level, smaller company, or partial fit)
30-49: Weak fit — limited alignment, low urgency, or unclear decision-making authority
0-29: Poor fit — wrong industry, no website, or very unlikely to benefit

WEIGHTING GUIDE:
- Decision maker seniority: 30 points max
- Pain points / urgency (website issues we can fix): 30 points max
- Industry fit: 20 points max
- Company size and growth signals: 20 points max

Return ONLY valid JSON — no explanation, no markdown:
{{"score": 72, "reason": "One specific sentence explaining the score referencing the most important factors."}}"""

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    score = max(0, min(100, int(data["score"])))
    reason = str(data.get("reason", f"Score of {score} based on lead and website intelligence."))
    return score, reason


# ── Public API ─────────────────────────────────────────────────────────────────

async def score_lead(lead, target_industry: str | None = None, db=None) -> tuple[int, str]:
    """
    Score a lead. Uses Claude with full website intelligence when available.
    Falls back to rule-based scoring if Claude is unavailable or fails.
    """
    # Try to load website scan for this lead
    scan = None
    if db is not None:
        try:
            from sqlalchemy import select
            from app.models.website_scan import WebsiteScan
            result = await db.execute(
                select(WebsiteScan).where(WebsiteScan.lead_id == lead.id)
            )
            scan = result.scalar_one_or_none()
        except Exception as e:
            logger.warning("[SCORE] Could not load scan for lead %s: %s", lead.email, e)

    # Claude scoring
    if settings.ANTHROPIC_API_KEY:
        try:
            score, reason = await _score_with_claude(lead, scan, target_industry)
            logger.info("[SCORE] Claude scored %s: %d — %s", lead.email, score, reason)
            return score, reason
        except Exception as e:
            logger.warning("[SCORE] Claude scoring failed for %s — falling back to rules: %s", lead.email, e)

    # Rule-based fallback
    score = _rule_based_score(
        title=lead.title,
        company_size=lead.company_size,
        industry=lead.industry,
        website=lead.website,
        target_industry=target_industry,
    )
    reason = f"Score of {score} based on title seniority, company size, and industry fit."
    logger.info("[SCORE] Rule-based scored %s: %d", lead.email, score)
    return score, reason
