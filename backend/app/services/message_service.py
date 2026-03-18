import logging
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.website_scan import WebsiteScan

logger = logging.getLogger(__name__)

LOOM_VIDEO_LINK = "https://www.instagram.com/reel/DV1MBFrAiKY/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA=="
CALENDAR_LINK = "https://calendar.app.google/fSPntmSnuAu5dFKu6"

GENERIC_OBSERVATION = (
    "I was looking at businesses like {{company}} and noticed a pattern that's quietly "
    "costing revenue — visitors who show interest but never take the next step."
)

_SUBJECT_OPTIONS = [
    "Quick question about {{company}}",
    "Small thing I noticed",
    "Quick observation",
]

_COLD_EMAIL_BODY = """\
Hi {{first_name}},

Quick question.

{{observation}}

In many cases, businesses lose potential customers when visitors can't clearly see the next step to book or get started.

We help companies fix this by building simple systems that capture leads and convert them into bookings automatically.

I recorded a quick 60-second video explaining exactly what I mean.

{{loom_video_link}}

If it makes sense, I'd be happy to show how this could work for {{company}}.

Hassan
Blackbird"""

_FOLLOWUP_1_BODY = """\
Hey {{first_name}},

Just following up on the email I sent earlier.

I recorded a quick video showing a small improvement that could help increase conversions for {{company}}.

In many cases businesses are losing leads simply because visitors don't immediately see the next step.

Here's the video again:
{{loom_video_link}}

Curious to hear your thoughts.

Hassan"""

_FOLLOWUP_2_BODY = """\
Hey {{first_name}},

One more quick follow-up.

I know inboxes get busy — but I didn't want to drop this without giving it a fair shot.

The short version: we help businesses like {{company}} capture more leads and convert them into booked appointments automatically, without needing to chase every inquiry manually.

If that's something worth a 15-minute conversation, here's my calendar:
{{calendar_link}}

If the timing isn't right, no problem at all. Happy to reconnect whenever works.

Hassan
Blackbird"""

_FOLLOWUP_3_BODY = """\
Hey {{first_name}},

Just closing the loop on this thread.

If the timing isn't right or this isn't relevant for {{company}}, totally understand — no hard feelings.

If things change and you ever want to explore improving lead capture or booking systems, feel free to reach back out.

Either way, best of luck with everything.

Hassan
Blackbird"""


def _fill(template: str, first_name: str, company: str, observation: str) -> str:
    return (
        template
        .replace("{{first_name}}", first_name)
        .replace("{{company}}", company)
        .replace("{{observation}}", observation)
        .replace("{{loom_video_link}}", LOOM_VIDEO_LINK)
        .replace("{{calendar_link}}", CALENDAR_LINK)
    )


def _pick_subject(lead_id: str, company: str) -> str:
    idx = abs(hash(lead_id)) % len(_SUBJECT_OPTIONS)
    return _SUBJECT_OPTIONS[idx].replace("{{company}}", company)


async def generate_messages(
    lead: "Lead",
    sender_name: str = "",
    sender_company: str = "",
    calendly_link: str = "",
    db: AsyncSession = None,
    scan: Optional["WebsiteScan"] = None,
) -> list[Message]:
    """
    Build cold_email + followup_1 + followup_2 + followup_3 from SOP templates.
    Uses website scan hook_text when available, generic fallback otherwise.
    Never regenerates if messages already exist for this lead.
    """
    # Cache check — never regenerate
    if db is not None:
        existing = await db.execute(
            select(Message).where(Message.lead_id == lead.id).limit(1)
        )
        if existing.scalar_one_or_none():
            logger.info("Messages already exist for lead %s — skipping generation", lead.email)
            all_msgs = await db.execute(select(Message).where(Message.lead_id == lead.id))
            return list(all_msgs.scalars().all())

        # Look up scan if not provided
        if scan is None:
            from app.models.website_scan import WebsiteScan
            scan_result = await db.execute(
                select(WebsiteScan).where(WebsiteScan.lead_id == lead.id)
            )
            scan = scan_result.scalar_one_or_none()

    first_name = lead.first_name or "there"
    company = lead.company or "your company"

    # Validate required fields
    if not lead.first_name:
        logger.warning("[MSG] Lead %s has no first_name — using 'there'", lead.email)
    if not lead.company:
        logger.warning("[MSG] Lead %s has no company — using 'your company'", lead.email)

    # Choose observation
    if scan and scan.hook_text:
        observation = scan.hook_text
    else:
        observation = GENERIC_OBSERVATION.replace("{{company}}", company)

    subject = _pick_subject(lead.id, company)
    followup_subject = f"Re: Quick question about {company}"

    templates = [
        ("cold_email",  subject,                   _fill(_COLD_EMAIL_BODY,   first_name, company, observation)),
        ("followup_1",  followup_subject,           _fill(_FOLLOWUP_1_BODY,  first_name, company, observation)),
        ("followup_2",  followup_subject,           _fill(_FOLLOWUP_2_BODY,  first_name, company, observation)),
        ("followup_3",  "Closing the loop",         _fill(_FOLLOWUP_3_BODY,  first_name, company, observation)),
    ]

    messages = []
    for msg_type, msg_subject, msg_body in templates:
        msg = Message(
            lead_id=lead.id,
            type=msg_type,
            subject=msg_subject,
            body=msg_body,
            status="pending",
        )
        if db is not None:
            db.add(msg)
        messages.append(msg)

    if db is not None:
        await db.flush()

    logger.info("Built %d SOP messages for lead %s (observation: %s)", len(messages), lead.email, observation[:40])
    return messages
