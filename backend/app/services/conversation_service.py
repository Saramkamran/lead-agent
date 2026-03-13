import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def classify_intent(reply_text: str) -> str:
    """
    Returns 'positive', 'neutral', or 'negative'.
    """
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=5,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Classify this email reply as exactly one word: positive, neutral, or negative.\n"
                        f"Reply: {reply_text}"
                    ),
                }
            ],
        )
        result = response.choices[0].message.content.strip().lower()
        if result not in ("positive", "neutral", "negative"):
            result = "neutral"
        logger.info("Intent classified as: %s", result)
        return result
    except Exception as e:
        logger.error("Failed to classify intent: %s", e)
        return "neutral"


async def generate_reply(conversation, lead, campaign) -> str:
    """
    Generate an AI reply for an active conversation.
    Appends both the inbound reply and AI response to conversation.thread.
    Returns the AI-generated reply text.
    """
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
        f"You are {campaign.sender_name or 'the sender'} from {campaign.sender_company or 'our company'}.\n"
        f"You are having an email conversation with {lead.first_name or lead.email}, "
        f"{lead.title or 'a professional'} at {lead.company or 'their company'}.\n"
        "Your goal is to book a 30-minute discovery call.\n"
        f"Calendly link: {campaign.calendly_link or ''}\n\n"
        "Rules:\n"
        "- Maximum 3 sentences per reply\n"
        "- Be warm and human, never pushy or salesy\n"
        "- If they want to meet: share the Calendly link in this reply\n"
        "- If they say they are not interested: thank them politely, wish them well, end the conversation\n"
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
        raise

    # Append AI response to thread
    thread.append({
        "role": "agent",
        "content": ai_reply,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    conversation.thread = list(thread)
    conversation.updated_at = datetime.now(timezone.utc)

    logger.info("Generated AI reply for conversation %s", conversation.id)
    return ai_reply
