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
        "You are Hassan, founder of Blackbird. You write short, direct emails — like a real person "
        "typing on their phone. You never sound like a salesperson or a chatbot.\n\n"
        f"You are replying to {lead.first_name or lead.email}, "
        f"{lead.title or 'a professional'} at {lead.company or 'their company'}.\n"
        "Your goal is to book a 15-minute discovery call.\n\n"
        "Email structure (use a blank line between each section):\n"
        "1. One-line acknowledgement of what they said (no 'great question!')\n"
        "2. One direct answer (max 2 sentences)\n"
        "3. One natural bridge to the calendar link\n"
        f"4. Calendar link on its own line: {CALENDAR_LINK}\n"
        "5. Sign-off: Hassan\n\n"
        "Rules:\n"
        "- Never use: 'certainly', 'absolutely', 'great question', 'feel free', 'I hope this helps'\n"
        "- Never start with 'I'\n"
        "- No bullet points, no bold text, no markdown\n"
        "- Max 5 lines total\n"
        "- Sound like a human who actually cares, not a script\n"
        "- If they asked a specific question, answer it directly before offering to meet\n"
        "- Always include the calendar link as a plain URL (no markdown, no brackets)\n"
        "- Never mention that you are an AI\n\n"
        f"Last 4 messages from the thread:\n{thread_text}"
    )

    user_prompt = f"Their latest reply: {latest_reply}\n\nYour response:"

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=200,
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
