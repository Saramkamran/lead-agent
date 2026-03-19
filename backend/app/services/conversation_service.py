import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


_VALID_INTENTS = frozenset([
    "interested", "question", "not_interested", "unsubscribe",
    "out_of_office", "wrong_person", "spam_complaint",
])


async def classify_intent(reply_text: str) -> str:
    """
    Returns one of: interested | question | not_interested | unsubscribe |
    out_of_office | wrong_person | spam_complaint.
    Falls back to 'question' on error or unrecognised output.
    """
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=10,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Classify this email reply as exactly one of these categories:\n"
                        "interested, question, not_interested, unsubscribe, out_of_office, wrong_person, spam_complaint\n\n"
                        "Rules:\n"
                        "- interested: wants to learn more, wants to meet, positive curiosity\n"
                        "- question: asking how it works, what it costs, follow-up questions\n"
                        "- not_interested: no thanks, not for us, not relevant\n"
                        "- unsubscribe: remove me, stop, unsubscribe, don't contact me\n"
                        "- out_of_office: auto-reply or OOO message\n"
                        "- wrong_person: I don't handle this, wrong contact\n"
                        "- spam_complaint: this is spam\n\n"
                        "Respond with exactly one word from the list.\n"
                        f"Reply: {reply_text}"
                    ),
                }
            ],
        )
        result = response.choices[0].message.content.strip().lower()
        if result not in _VALID_INTENTS:
            result = "question"
        logger.info("Intent classified as: %s", result)
        return result
    except Exception as e:
        logger.error("Failed to classify intent: %s", e)
        return "question"


async def generate_reply(conversation, lead, campaign) -> str:
    """
    Generate an AI reply for an active conversation.
    Appends both the inbound reply and AI response to conversation.thread.
    Returns the AI-generated reply text.
    """
    from app.services.scan_service import CALENDAR_LINK

    thread: list = conversation.thread or []

    # Build last 4 messages context
    last_4 = thread[-4:] if len(thread) >= 4 else thread
    thread_text = "\n".join(
        f"{entry.get('role', 'unknown').upper()}: {entry.get('content', '')}"
        for entry in last_4
    )

    # Latest reply is the last inbound entry
    latest_reply = ""
    for entry in reversed(thread):
        if entry.get("role") == "lead":
            latest_reply = entry.get("content", "")
            break

    system_prompt = (
        "You are Hassan from Blackbird.\n"
        f"You are having an email conversation with {lead.first_name or lead.email}, "
        f"{lead.title or 'a professional'} at {lead.company or 'their company'}.\n"
        "Your goal is to book a 15-minute discovery call.\n"
        f"Calendar link: {CALENDAR_LINK}\n\n"
        "Rules:\n"
        "- Maximum 3 sentences per reply\n"
        "- Be warm and human, never pushy or salesy\n"
        "- Always include the calendar link as a plain URL (no markdown, no brackets)\n"
        "- Never write links as [text](url) — write the raw URL directly\n"
        "- If they want to meet: share the calendar link in this reply\n"
        "- If they ask a question: answer briefly then offer the calendar link\n"
        "- Never mention that you are an AI\n"
        "- Do not repeat information already covered in the thread\n\n"
        f"Last 4 messages from the thread:\n{thread_text}"
    )

    user_prompt = f"Their latest reply: {latest_reply}\n\nYour response:"

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=150,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Failed to generate reply for conversation %s: %s", conversation.id, e)
        return ""

    # Append AI response to thread
    thread.append({
        "role": "agent",
        "content": ai_reply,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    conversation.thread = list(thread)
    flag_modified(conversation, "thread")
    conversation.updated_at = datetime.now(timezone.utc)

    logger.info("Generated AI reply for conversation %s", conversation.id)
    return ai_reply
