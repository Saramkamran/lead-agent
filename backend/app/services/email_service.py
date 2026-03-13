import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    from_email: str,
    from_name: str,
) -> str:
    """
    Send an email via Brevo Transactional API.
    Returns the Brevo messageId on success, '' on failure.
    Never raises — background jobs must continue on email errors.
    """
    payload = {
        "sender": {"name": from_name, "email": from_email},
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "textContent": body,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                BREVO_SEND_URL,
                headers={
                    "api-key": settings.BREVO_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code in (200, 201):
            message_id = response.json().get("messageId", "")
            logger.info(
                "[EMAIL] Sent to %s — messageId: %s",
                to_email,
                message_id,
            )
            return message_id

        logger.error(
            "[EMAIL] Brevo API error at %s — status %d: %s",
            datetime.now(timezone.utc).isoformat(),
            response.status_code,
            response.text,
        )
        return ""

    except Exception as e:
        logger.error(
            "[EMAIL] Failed to send to %s at %s: %s",
            to_email,
            datetime.now(timezone.utc).isoformat(),
            e,
        )
        return ""
