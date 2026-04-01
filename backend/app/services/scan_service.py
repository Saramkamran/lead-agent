import json
import logging
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.website_scan import WebsiteScan

logger = logging.getLogger(__name__)

LOOM_VIDEO_LINK = "https://www.instagram.com/reel/DV1MBFrAiKY/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA=="
CALENDAR_LINK = "https://calendar.app.google/fSPntmSnuAu5dFKu6"

HOOK_TEXTS: dict[str, str] = {
    "no_booking": "I checked your website and noticed that visitors can't directly book or schedule from the site.",
    "no_pricing": "I checked your website and noticed there isn't a pricing section for your services.",
    "weak_cta": "I checked your website and noticed there isn't a clear next step for visitors who want to get started.",
    "no_lead_capture": "I checked your website and noticed there isn't a way for potential customers to quickly submit an inquiry.",
    "general": "I checked your website and noticed a few things that might be worth a quick look.",
}

# Keywords used to find priority sub-pages
_PRIORITY_KEYWORDS = ["service", "pricing", "price", "contact", "about", "booking", "book", "offering"]

# Social media platform detection patterns
_SOCIAL_PATTERNS: dict[str, list[str]] = {
    "linkedin": ["linkedin.com/company/", "linkedin.com/in/"],
    "facebook": ["facebook.com/", "fb.com/"],
    "instagram": ["instagram.com/"],
    "twitter": ["twitter.com/", "x.com/"],
    "tiktok": ["tiktok.com/@"],
    "youtube": ["youtube.com/channel/", "youtube.com/user/", "youtube.com/@"],
}


def _normalise_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _same_domain(base: str, link: str) -> bool:
    try:
        base_host = urlparse_netloc(base)
        link_host = urlparse_netloc(link)
        return link_host == base_host or link_host == ""
    except Exception:
        return False


def urlparse_netloc(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower().lstrip("www.")


def _page_to_text(html: str, max_chars: int = 3000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_social_links(html: str) -> dict[str, str]:
    """Extract social media profile URLs from website HTML."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        href_lower = href.lower()
        for platform, patterns in _SOCIAL_PATTERNS.items():
            if platform not in found:
                for pattern in patterns:
                    if pattern in href_lower:
                        found[platform] = href
                        break
    return found


async def fetch_pages(url: str) -> tuple[list[str], str]:
    """
    Fetch homepage + up to 3 priority sub-pages.
    Returns (list of plain-text strings, raw homepage HTML).
    """
    url = _normalise_url(url)
    if not url:
        return [], ""

    from urllib.parse import urljoin, urlparse

    pages_text: list[str] = []
    homepage_html = ""

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadScanner/1.0)"},
        ) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                homepage_html = resp.text
                pages_text.append(_page_to_text(homepage_html))
            except Exception as e:
                logger.warning("[SCAN] Failed to fetch homepage %s: %s", url, e)
                return [], ""

            # Find priority sub-pages from homepage links
            soup = BeautifulSoup(homepage_html, "html.parser")
            candidate_links: list[str] = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                full = urljoin(url, href)
                if not _same_domain(url, full):
                    continue
                text_lower = (a.get_text() + href).lower()
                if any(kw in text_lower for kw in _PRIORITY_KEYWORDS):
                    if full not in candidate_links:
                        candidate_links.append(full)

            # Fetch up to 3 sub-pages (expanded from 2)
            fetched_sub = 0
            for link in candidate_links:
                if fetched_sub >= 3:
                    break
                try:
                    r = await client.get(link)
                    r.raise_for_status()
                    pages_text.append(_page_to_text(r.text))
                    fetched_sub += 1
                except Exception as e:
                    logger.debug("[SCAN] Sub-page fetch failed %s: %s", link, e)

    except Exception as e:
        logger.error("[SCAN] Unexpected error fetching %s: %s", url, e)
        return [], ""

    return pages_text, homepage_html


async def _duckduckgo_search(query: str) -> list[str]:
    """
    Query DuckDuckGo Instant Answer API and return text snippets.
    Returns up to ~5 snippet strings, empty list on any error.
    """
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LeadScanner/1.0)"})
            data = resp.json()

        snippets: list[str] = []
        if data.get("AbstractText"):
            snippets.append(data["AbstractText"][:350])
        for topic in data.get("RelatedTopics", [])[:6]:
            if isinstance(topic, dict) and topic.get("Text"):
                snippets.append(topic["Text"][:150])
        return snippets
    except Exception as e:
        logger.debug("[SCAN] DuckDuckGo search failed for '%s': %s", query, e)
        return []


async def gather_web_intelligence(company_name: str, website: str, homepage_html: str) -> dict:
    """
    Gather external intelligence about the company:
    - DuckDuckGo search for company news / recent activity
    - DuckDuckGo search for company reviews / reputation
    - Social media links extracted from the website HTML

    Returns dict with keys: news_snippets, review_snippets, social_links
    """
    domain = ""
    if website:
        from urllib.parse import urlparse
        domain = urlparse(_normalise_url(website)).netloc.lstrip("www.")

    # Run searches in parallel
    news_q = f'"{company_name}" {domain} news' if company_name else domain
    reviews_q = f'"{company_name}" reviews ratings' if company_name else ""

    results = await _duckduckgo_search(news_q) if news_q else []
    review_results = await _duckduckgo_search(reviews_q) if reviews_q else []

    social_links = _extract_social_links(homepage_html) if homepage_html else {}

    return {
        "news_snippets": results,
        "review_snippets": review_results,
        "social_links": social_links,
    }


async def analyze_with_claude(
    pages_text: list[str],
    company_name: str = "",
    web_intel: Optional[dict] = None,
) -> dict:
    """
    Send all gathered intelligence to Claude claude-haiku-4-5-20251001.
    Returns a rich dict with website analysis, pain points, growth signals,
    trust signals, urgency, and connection angle.
    Falls back to safe defaults on error.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("[SCAN] ANTHROPIC_API_KEY not set — using defaults")
        return _default_scan_data()

    # Build website section
    website_section = "\n\n---\n\n".join(
        f"[Page {i+1}]\n{text}" for i, text in enumerate(pages_text)
    )

    # Build research section
    intel = web_intel or {}
    news_snippets = intel.get("news_snippets", [])
    review_snippets = intel.get("review_snippets", [])
    social_links = intel.get("social_links", {})

    research_section = ""
    if news_snippets:
        combined_news = " | ".join(news_snippets[:4])[:500]
        research_section += f"\nNews / recent activity about {company_name}:\n{combined_news}\n"
    if review_snippets:
        combined_reviews = " | ".join(review_snippets[:3])[:400]
        research_section += f"\nReviews / reputation:\n{combined_reviews}\n"
    if social_links:
        platforms = ", ".join(social_links.keys())
        research_section += f"\nSocial media presence: {platforms}\n"

    prompt = f"""You are analyzing a business prospect for cold outreach. Extract structured intelligence from their website and research data.

Company name: {company_name or "unknown"}

WEBSITE CONTENT:
{website_section}

EXTERNAL RESEARCH:
{research_section if research_section else "No external research available."}

Return a JSON object with EXACTLY these fields:

{{
  "business_type": "brief description of what this company does (1 sentence)",
  "services_list": "comma-separated list of main services/products",
  "has_pricing_page": true or false,
  "has_booking_system": true or false,
  "has_contact_form": true or false,
  "cta_strength": "none" or "weak" or "strong",
  "lead_capture_forms": true or false,
  "design_quality": "basic" or "standard" or "professional",
  "booking_method": "phone_only" or "email_only" or "form_only" or "calendar" or "none",
  "pain_points": ["specific problem 1 observed on their site", "specific problem 2", "specific problem 3"],
  "growth_signals": ["growth indicator 1 from news/research", "growth indicator 2"],
  "trust_signals": ["social proof signal 1", "signal 2"],
  "urgency_level": "low" or "medium" or "high",
  "connection_angle": "The single most specific and compelling observation about THIS business to open a cold email. Reference something concrete — a specific gap, recent news, or opportunity. Max 35 words. Sound human.",
  "personalized_opener": "One sentence (max 30 words) cold email opener mentioning something specific about {company_name}'s site. E.g.: 'I noticed [Company] offers [service] but visitors can\\'t book directly from the homepage.'"
}}

Rules:
- has_booking_system: true only if there is a live Calendly, Acuity, booking widget, or 'Book Now' button
- urgency_level 'high': business has no booking system AND no pricing AND weak/no CTA
- urgency_level 'medium': missing 1-2 of the above
- urgency_level 'low': mostly set up, minor gaps only
- pain_points: be specific to THIS business, not generic (e.g. "No way to book appointments online" not "missing features")
- growth_signals: empty array if no signals found — do NOT invent signals
- trust_signals: look for reviews mentions, years in business, certifications, client counts
- connection_angle must mention {company_name} by name if provided
- Return valid JSON only. No explanation. No markdown."""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return data
    except json.JSONDecodeError as e:
        logger.error("[SCAN] JSON parse error from Claude: %s", e)
        return _default_scan_data()
    except Exception as e:
        logger.error("[SCAN] Claude API error: %s", e)
        return _default_scan_data()


def _default_scan_data() -> dict:
    return {
        "business_type": None,
        "services_list": None,
        "has_pricing_page": False,
        "has_booking_system": False,
        "has_contact_form": False,
        "cta_strength": "none",
        "lead_capture_forms": False,
        "design_quality": None,
        "booking_method": "none",
        "pain_points": [],
        "growth_signals": [],
        "trust_signals": [],
        "urgency_level": "medium",
        "connection_angle": "",
        "personalized_opener": "",
    }


def detect_problem(scan_data: dict) -> tuple[str, str]:
    """
    Apply SOP priority rules to return (problem_key, hook_text).
    Priority 1→5 per spec.
    """
    if not scan_data.get("has_booking_system") and scan_data.get("booking_method") != "calendar":
        return ("no_booking", HOOK_TEXTS["no_booking"])
    if not scan_data.get("has_pricing_page"):
        return ("no_pricing", HOOK_TEXTS["no_pricing"])
    cta = (scan_data.get("cta_strength") or "none").lower()
    if cta in ("none", "weak"):
        return ("weak_cta", HOOK_TEXTS["weak_cta"])
    if not scan_data.get("has_contact_form") and not scan_data.get("lead_capture_forms"):
        return ("no_lead_capture", HOOK_TEXTS["no_lead_capture"])
    return ("general", HOOK_TEXTS["general"])


async def scan_website(lead: "Lead", db: AsyncSession) -> Optional["WebsiteScan"]:
    """
    Full intelligence pipeline:
    1. Fetch website pages (homepage + up to 3 sub-pages)
    2. Gather web intelligence (news search, reviews, social links)
    3. Analyze everything with Claude — pain points, growth signals, urgency
    4. Save enriched WebsiteScan to DB.
    If another lead with the same website was already scanned, reuse that scan
    instead of making duplicate API calls.
    """
    from app.models.lead import Lead as LeadModel
    from app.models.website_scan import WebsiteScan
    from sqlalchemy import select

    if not lead.website:
        logger.warning("[SCAN] Lead %s has no website — skipping scan", lead.email)
        return None

    normalised = _normalise_url(lead.website)

    # Check for an existing scan on another lead with the same website
    existing_result = await db.execute(
        select(WebsiteScan)
        .join(LeadModel, WebsiteScan.lead_id == LeadModel.id)
        .where(LeadModel.website == normalised, LeadModel.id != lead.id)
        .order_by(WebsiteScan.scanned_at.desc())
        .limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        ws_copy = WebsiteScan(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            business_type=existing.business_type,
            services_list=existing.services_list,
            has_pricing_page=existing.has_pricing_page,
            has_booking_system=existing.has_booking_system,
            has_contact_form=existing.has_contact_form,
            cta_strength=existing.cta_strength,
            lead_capture_forms=existing.lead_capture_forms,
            design_quality=existing.design_quality,
            booking_method=existing.booking_method,
            detected_problem=existing.detected_problem,
            hook_text=existing.hook_text,
            pain_points=existing.pain_points,
            growth_signals=existing.growth_signals,
            trust_signals=existing.trust_signals,
            social_links=existing.social_links,
            urgency_level=existing.urgency_level,
            connection_angle=existing.connection_angle,
            reused_from=normalised,
            scanned_at=datetime.now(timezone.utc),
        )
        db.add(ws_copy)
        await db.flush()
        logger.info("[SCAN] Reused existing scan for %s (lead %s)", normalised, lead.email)
        return ws_copy

    pages_text, homepage_html = await fetch_pages(lead.website)
    if not pages_text:
        logger.warning("[SCAN] No pages fetched for lead %s (%s)", lead.email, lead.website)
        return None

    company_name = lead.company or ""

    # Gather external intelligence in parallel with a gather call
    web_intel = await gather_web_intelligence(company_name, lead.website, homepage_html)

    # Deep Claude analysis with all gathered data
    scan_data = await analyze_with_claude(
        pages_text,
        company_name=company_name,
        web_intel=web_intel,
    )

    problem_key, hook_text = detect_problem(scan_data)

    # Use connection_angle as hook if available; fall back to personalized_opener; then generic hook
    connection_angle = (scan_data.get("connection_angle") or "").strip()
    personalized_opener = (scan_data.get("personalized_opener") or "").strip()
    if connection_angle:
        hook_text = connection_angle
    elif personalized_opener:
        hook_text = personalized_opener

    # Serialize list/dict fields to JSON strings
    pain_points_json = json.dumps(scan_data.get("pain_points") or [])
    growth_signals_json = json.dumps(scan_data.get("growth_signals") or [])
    trust_signals_json = json.dumps(scan_data.get("trust_signals") or [])
    social_links_json = json.dumps(web_intel.get("social_links") or {})

    ws = WebsiteScan(
        id=str(uuid.uuid4()),
        lead_id=lead.id,
        business_type=scan_data.get("business_type"),
        services_list=scan_data.get("services_list"),
        has_pricing_page=scan_data.get("has_pricing_page"),
        has_booking_system=scan_data.get("has_booking_system"),
        has_contact_form=scan_data.get("has_contact_form"),
        cta_strength=scan_data.get("cta_strength"),
        lead_capture_forms=scan_data.get("lead_capture_forms"),
        design_quality=scan_data.get("design_quality"),
        booking_method=scan_data.get("booking_method"),
        detected_problem=problem_key,
        hook_text=hook_text,
        pain_points=pain_points_json,
        growth_signals=growth_signals_json,
        trust_signals=trust_signals_json,
        social_links=social_links_json,
        urgency_level=scan_data.get("urgency_level") or "medium",
        connection_angle=connection_angle or personalized_opener,
        scanned_at=datetime.now(timezone.utc),
    )
    db.add(ws)
    await db.flush()
    logger.info(
        "[SCAN] %s — problem: %s | urgency: %s | pain_points: %d | growth_signals: %d | social: %s",
        lead.website,
        problem_key,
        ws.urgency_level,
        len(scan_data.get("pain_points") or []),
        len(scan_data.get("growth_signals") or []),
        ", ".join(web_intel.get("social_links", {}).keys()) or "none",
    )
    return ws
