import asyncio
import email.parser
import email.policy
import email.utils
import logging
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from uuid import uuid4

import aiosmtplib
import aioimaplib
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_message(
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str | None = None,
    reply_to_message_id: str | None = None,
    thread_references: str | None = None,
) -> tuple[EmailMessage, str]:
    """Build an EmailMessage and return it along with the generated Message-ID."""
    domain = settings.SMTP_FROM_EMAIL.split("@")[-1] if "@" in settings.SMTP_FROM_EMAIL else "localhost"
    message_id = f"<{uuid4()}@{domain}>"

    msg = EmailMessage()
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>" if settings.SMTP_FROM_NAME else settings.SMTP_FROM_EMAIL
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["Message-ID"] = message_id

    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        refs = thread_references or reply_to_message_id
        msg["References"] = refs

    plain = body_text or BeautifulSoup(body_html, "html.parser").get_text(separator="\n").strip()
    msg.set_content(plain)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    return msg, message_id


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str | None = None,
    reply_to_message_id: str | None = None,
    thread_references: str | None = None,
) -> str:
    """
    Send an email via SMTP (aiosmtplib).
    Returns the Message-ID string on success, '' on failure.
    Never raises — background jobs must continue on email errors.
    """
    try:
        msg, message_id = _build_message(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            reply_to_message_id=reply_to_message_id,
            thread_references=thread_references,
        )

        use_tls = settings.SMTP_PORT == 465
        # Disable cert verification for cPanel/shared hosting (cert is for host, not domain)
        _ssl_ctx = ssl.create_default_context()
        _ssl_ctx.check_hostname = False
        _ssl_ctx.verify_mode = ssl.CERT_NONE
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASS,
            start_tls=not use_tls,
            use_tls=use_tls,
            tls_context=_ssl_ctx,
        )

        logger.info("[EMAIL] Sent to %s — Message-ID: %s", to_email, message_id)
        return message_id

    except Exception as e:
        logger.error(
            "[EMAIL] Failed to send to %s at %s: %s",
            to_email,
            datetime.now(timezone.utc).isoformat(),
            e,
        )
        return ""


async def poll_imap_replies(handle_reply_callback) -> None:
    """
    Long-running asyncio loop that polls IMAP for unseen messages.
    Calls handle_reply_callback(reply_data) for each new message.
    Never crashes — exceptions are caught, logged, and the loop continues.
    """
    logger.info("[IMAP] Polling loop started (interval: %ds)", settings.IMAP_POLL_INTERVAL_SECONDS)

    while True:
        try:
            # Disable cert verification for cPanel/shared hosting
            _imap_ssl = ssl.create_default_context()
            _imap_ssl.check_hostname = False
            _imap_ssl.verify_mode = ssl.CERT_NONE
            imap = aioimaplib.IMAP4_SSL(host=settings.IMAP_HOST, port=settings.IMAP_PORT, ssl_context=_imap_ssl)
            await imap.wait_hello_from_server()
            await imap.login(settings.IMAP_USER, settings.IMAP_PASS)
            await imap.select(settings.IMAP_REPLY_FOLDER)

            _, data = await imap.search("UNSEEN")
            uids = data[0].split() if data and data[0] else []

            for uid in uids:
                try:
                    _, msg_data = await imap.fetch(uid, "(RFC822)")
                    raw = msg_data[1] if len(msg_data) > 1 else None
                    if not raw:
                        continue

                    parser = email.parser.BytesParser(policy=email.policy.default)
                    parsed = parser.parsebytes(raw)

                    from_field = parsed.get("From", "")
                    from_email = email.utils.parseaddr(from_field)[1].strip().lower()
                    subject = parsed.get("Subject", "")
                    msg_id = parsed.get("Message-ID", "").strip()
                    in_reply_to = parsed.get("In-Reply-To", "").strip()
                    references = parsed.get("References", "").strip()

                    # Extract plain text body
                    body = ""
                    if parsed.is_multipart():
                        for part in parsed.walk():
                            ct = part.get_content_type()
                            if ct == "text/plain":
                                body = part.get_content()
                                break
                            elif ct == "text/html" and not body:
                                body = BeautifulSoup(part.get_content(), "html.parser").get_text(separator="\n").strip()
                    else:
                        ct = parsed.get_content_type()
                        if ct == "text/plain":
                            body = parsed.get_content()
                        elif ct == "text/html":
                            body = BeautifulSoup(parsed.get_content(), "html.parser").get_text(separator="\n").strip()

                    reply_data = {
                        "from_email": from_email,
                        "subject": subject,
                        "body": body.strip() if body else "",
                        "message_id": msg_id,
                        "in_reply_to": in_reply_to,
                        "references": references,
                    }

                    await handle_reply_callback(reply_data)

                    # Mark as Seen
                    await imap.uid("store", uid.decode() if isinstance(uid, bytes) else uid, "+FLAGS", "\\Seen")

                except Exception as e:
                    logger.error("[IMAP] Error processing message uid %s: %s", uid, e)

            await imap.logout()

        except Exception as e:
            logger.error("[IMAP] Poll cycle error at %s: %s", datetime.now(timezone.utc).isoformat(), e)

        await asyncio.sleep(settings.IMAP_POLL_INTERVAL_SECONDS)
