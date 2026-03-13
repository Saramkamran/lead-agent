"""Tests for the rule-based lead scoring engine.

calculate_score() is a pure synchronous function — no LLM involved.
score_lead() wraps it and calls gpt-4o-mini only for generating the
human-readable reason; that call is mocked in these tests.
"""

from unittest.mock import AsyncMock, patch

from app.services.scoring_service import calculate_score, score_lead


# ── calculate_score — pure function, no mocking needed ────────────────────────

def test_ceo_large_company_matching_industry_with_website():
    score = calculate_score(
        title="CEO",
        company_size="500+",
        industry="SaaS",
        website="acme.com",
        target_industry="SaaS",
    )
    # 30 (CEO) + 30 (500+) + 20 (industry match) + 10 (website) = 90
    assert score == 90


def test_vp_mid_size_industry_no_match():
    score = calculate_score(
        title="VP of Sales",
        company_size="100-499",
        industry="Real Estate",
        website="re.com",
        target_industry="SaaS",
    )
    # 25 (VP) + 25 (100-499) + 0 (no match) + 10 (website) = 60
    assert score == 60


def test_manager_small_company_no_industry():
    score = calculate_score(
        title="Operations Manager",
        company_size="10-49",
        industry="Retail",
        website=None,
        target_industry=None,
    )
    # 15 (manager) + 10 (10-49) + 0 + 0 = 25
    assert score == 25


def test_default_title_smallest_company_no_website():
    """Unknown title gets 8 pts; missing/unknown size gets 5 pts."""
    score = calculate_score(
        title="Analyst",
        company_size="1-10",
        industry="Finance",
        website="",
        target_industry=None,
    )
    # 8 (default) + 5 (1-10) + 0 + 0 = 13
    assert score == 13


def test_no_title_no_size_no_industry():
    score = calculate_score(
        title=None,
        company_size=None,
        industry=None,
        website=None,
        target_industry=None,
    )
    # 8 (default title) + 5 (default size) = 13
    assert score == 13


def test_founder_title_recognised():
    score = calculate_score(
        title="Co-Founder",
        company_size="100-499",
        industry=None,
        website=None,
        target_industry=None,
    )
    # 30 (founder) + 25 (100-499) = 55
    assert score == 55


def test_president_title_recognised():
    score = calculate_score(
        title="President",
        company_size="50-200",
        industry=None,
        website=None,
        target_industry=None,
    )
    # 30 (president) + 18 (50-200) = 48
    assert score == 48


def test_director_title_recognised():
    score = calculate_score(
        title="Director of Marketing",
        company_size="50-200",
        industry=None,
        website="company.com",
        target_industry="SaaS",
    )
    # 25 (director) + 18 (50-200) + 0 (industry=None) + 10 (website) = 53
    assert score == 53


def test_head_of_title_recognised():
    score = calculate_score(
        title="Head of Growth",
        company_size="10-49",
        industry=None,
        website=None,
        target_industry=None,
    )
    # 15 (head of) + 10 (10-49) = 25
    assert score == 25


def test_industry_match_is_case_insensitive():
    score_match = calculate_score(
        title="Manager", company_size="10-49",
        industry="saas", website=None, target_industry="SaaS",
    )
    score_no_match = calculate_score(
        title="Manager", company_size="10-49",
        industry="retail", website=None, target_industry="SaaS",
    )
    assert score_match - score_no_match == 20


def test_website_blank_string_does_not_add_points():
    score_with = calculate_score("CEO", "500+", None, "acme.com", None)
    score_without = calculate_score("CEO", "500+", None, "   ", None)
    assert score_with - score_without == 10


def test_score_capped_at_100():
    """No matter the inputs, score must never exceed 100."""
    score = calculate_score(
        title="CEO",
        company_size="500+",
        industry="SaaS",
        website="example.com",
        target_industry="SaaS",
    )
    assert score <= 100


def test_no_target_industry_gives_zero_industry_points():
    score_with_target = calculate_score("CEO", "500+", "SaaS", None, "SaaS")
    score_no_target = calculate_score("CEO", "500+", "SaaS", None, None)
    assert score_with_target - score_no_target == 20


# ── score_lead — async, mocks the OpenAI reason call ──────────────────────────

async def test_calculate_score_never_calls_llm():
    """The pure calculate_score() must never instantiate an OpenAI client."""
    with patch("app.services.scoring_service._get_client") as mock_get_client:
        calculate_score("CEO", "500+", "SaaS", "site.com", "SaaS")
        mock_get_client.assert_not_called()


async def test_score_lead_returns_score_and_reason():
    mock_response = AsyncMock()
    mock_response.choices[0].message.content = "Strong lead — CEO of a large SaaS company."

    with patch("app.services.scoring_service._get_client") as mock_get_client:
        mock_get_client.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        class FakeLead:
            email = "test@example.com"
            title = "CEO"
            company_size = "500+"
            industry = "SaaS"
            website = "site.com"

        score, reason = await score_lead(FakeLead(), target_industry="SaaS")

    assert isinstance(score, int)
    assert 0 <= score <= 100
    assert isinstance(reason, str)
    assert len(reason) > 0


async def test_score_lead_reason_fallback_on_openai_error():
    """If OpenAI fails, score_lead should still return a fallback reason string."""
    with patch("app.services.scoring_service._get_client") as mock_get_client:
        mock_get_client.return_value.chat.completions.create = AsyncMock(
            side_effect=Exception("API unavailable")
        )

        class FakeLead:
            email = "fallback@example.com"
            title = "Manager"
            company_size = "10-49"
            industry = "Retail"
            website = None

        score, reason = await score_lead(FakeLead(), target_industry=None)

    assert isinstance(score, int)
    assert isinstance(reason, str)
    assert len(reason) > 0
