import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin, urlparse

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


def _normalise_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _same_domain(base: str, link: str) -> bool:
    try:
        base_host = urlparse(base).netloc.lower().lstrip("www.")
        link_host = urlparse(link).netloc.lower().lstrip("www.")
        return link_host == base_host or link_host == ""
    except Exception:
        return False


def _page_to_text(html: str, max_chars: int = 3000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    import re
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


async def fetch_pages(url: str) -> list[str]:
    """
    Fetch homepage + up to 2 priority sub-pages.
    Returns list of plain-text strings (up to 3 items).
    """
    url = _normalise_url(url)
    if not url:
        return []

    pages_text: list[str] = []

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadScanner/1.0)"},
        ) as client:
            # 1. Fetch homepage
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                homepage_html = resp.text
                pages_text.append(_page_to_text(homepage_html))
            except Exception as e:
                logger.warning("[SCAN] Failed to fetch homepage %s: %s", url, e)
                return []

            # 2. Find priority sub-pages from homepage links
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

            # 3. Fetch up to 2 sub-pages
            fetched_sub = 0
            for link in candidate_links:
                if fetched_sub >= 2:
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
        return []

    return pages_text


async def fetch_company_news(company_name: str, domain: str) -> str:
    """
    Fetch a short news snippet about the company using DuckDuckGo Instant Answer API.
    Returns a snippet (up to 250 chars) or empty string on any error.
    """
    try:
        query = f'"{company_name}" {domain}'
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_redirect=1"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LeadScanner/1.0)"})
            data = resp.json()
            abstract = data.get("AbstractText", "").strip()
            return abstract[:250] if abstract else ""
    except Exception as e:
        logger.debug("[SCAN] News fetch failed for %s: %s", company_name, e)
        return ""


async def analyze_with_claude(pages_text: list[str], company_name: str = "", news_snippet: str = "") -> dict:
    """
    Send page text to Claude claude-haiku-4-5-20251001 and extract structured website data.
    Returns a dict with detection fields; falls back to safe defaults on error.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("[SCAN] ANTHROPIC_API_KEY not set — using defaults")
        return _default_scan_data()

    combined = "\n\n---\n\n".join(
        f"[Page {i+1}]\n{text}" for i, text in enumerate(pages_text)
    )

    news_section = ""
    if news_snippet:
        news_section = f"""
Recent company news (use only if relevant and specific to this business):
{news_snippet}

If the news contains a recent event (funding, expansion, new product, award), reference it in the personalized_opener. Skip it if news is empty or irrelevant.
"""

    prompt = f"""Analyse the following website content and return a JSON object with these exact fields:

{{
  "business_type": "brief description of what this company does",
  "services_list": "comma-separated list of services/products offered",
  "has_pricing_page": true or false,
  "has_booking_system": true or false,
  "has_contact_form": true or false,
  "cta_strength": "none" or "weak" or "strong",
  "lead_capture_forms": true or false,
  "design_quality": "basic" or "standard" or "professional",
  "booking_method": "phone_only" or "email_only" or "form_only" or "calendar" or "none",
  "personalized_opener": "One specific sentence (max 30 words) for a cold email opening. Mention one concrete thing noticed about THIS specific business's site. Sound human. E.g.: 'I noticed [Company] offers [service] but visitors can\\'t book directly from the homepage.' Leave blank string if nothing specific found."
}}

Rules:
- has_booking_system: true if there is a Calendly, Acuity, booking widget, or "Book Now" button
- has_pricing_page: true if prices or packages are listed
- has_contact_form: true if there is any web form for inquiries
- cta_strength: "strong" = prominent clear call-to-action, "weak" = vague or buried CTA, "none" = no CTA
- lead_capture_forms: true if any form captures name/email
- booking_method: "calendar" if online calendar booking exists, else best match
- personalized_opener: must reference the specific company name "{company_name}" if provided
{news_section}
Website content:
{combined}

Return valid JSON only. No explanation. No markdown."""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
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
    Full pipeline: fetch pages → analyse with Claude → detect problem → save WebsiteScan.
    Returns the saved WebsiteScan object, or None if fetching failed entirely.
    """
    from app.models.website_scan import WebsiteScan

    if not lead.website:
        logger.warning("[SCAN] Lead %s has no website — skipping scan", lead.email)
        return None

    pages_text = await fetch_pages(lead.website)
    if not pages_text:
        logger.warning("[SCAN] No pages fetched for lead %s (%s)", lead.email, lead.website)
        return None

    company_name = lead.company or ""
    domain = lead.website or ""
    news_snippet = await fetch_company_news(company_name, domain) if company_name else ""

    scan_data = await analyze_with_claude(pages_text, company_name=company_name, news_snippet=news_snippet)
    problem_key, hook_text = detect_problem(scan_data)

    # Use personalized opener from Claude if available, else fall back to generic hook_text
    personalized_opener = (scan_data.get("personalized_opener") or "").strip()
    if personalized_opener:
        hook_text = personalized_opener

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
        scanned_at=datetime.now(timezone.utc),
    )
    db.add(ws)
    await db.flush()
    logger.info("[SCAN] Scanned %s — problem: %s", lead.website, problem_key)
    return ws
