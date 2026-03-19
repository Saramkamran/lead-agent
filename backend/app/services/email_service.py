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


_SPAM_WORDS = [
    "guarantee", "guaranteed", "free", "click here", "limited time",
    "act now", "offer expires", "winner", "cash", "earn money",
    "make money", "risk free", "no cost", "congratulations",
    "this is not spam", "buy now", "order now", "special promotion",
]


def _check_spam_words(body: str) -> list[str]:
    lower = body.lower()
    return [w for w in _SPAM_WORDS if w in lower]


def _build_message(
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str | None = None,
    reply_to_message_id: str | None = None,
    thread_references: str | None = None,
    from_name: str | None = None,
    from_email: str | None = None,
    plain_text_only: bool = False,
) -> tuple[EmailMessage, str]:
    """Build an EmailMessage and return it along with the generated Message-ID."""
    _from_email = from_email or settings.SMTP_FROM_EMAIL
    _from_name = from_name or settings.SMTP_FROM_NAME

    domain = _from_email.split("@")[-1] if "@" in _from_email else "localhost"
    message_id = f"<{uuid4()}@{domain}>"

    msg = EmailMessage()
    msg["From"] = f"{_from_name} <{_from_email}>" if _from_name else _from_email
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["Message-ID"] = message_id

    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        refs = thread_references or reply_to_message_id
        msg["References"] = refs

    if plain_text_only:
        # Body is already plain text — use it directly, never run through HTML parser
        plain = body_text or body_html
    else:
        plain = body_text or BeautifulSoup(body_html, "html.parser").get_text(separator="\n").strip()
    msg.set_content(plain)
    if body_html and not plain_text_only:
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
    *,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_pass: str | None = None,
    from_name: str | None = None,
    from_email: str | None = None,
    plain_text_only: bool = False,
) -> str:
    """
    Send an email via SMTP (aiosmtplib).
    Returns the Message-ID string on success, '' on failure.
    Never raises — background jobs must continue on email errors.

    Optional per-account kwargs (smtp_host, smtp_port, smtp_user, smtp_pass, from_name,
    from_email) override the global env vars when provided.
    """
    _smtp_host = smtp_host or settings.SMTP_HOST
    _smtp_port = smtp_port or settings.SMTP_PORT
    _smtp_user = smtp_user or settings.SMTP_USER
    _smtp_pass = smtp_pass or settings.SMTP_PASS

    # Warn on spam words before sending
    spam_matches = _check_spam_words(body_html)
    if spam_matches:
        logger.warning("[EMAIL] Spam word warning for %s: %s", to_email, spam_matches)

    try:
        msg, message_id = _build_message(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            reply_to_message_id=reply_to_message_id,
            thread_references=thread_references,
            from_name=from_name,
            from_email=from_email,
            plain_text_only=plain_text_only,
        )

        use_tls = _smtp_port == 465
        _ssl_ctx = ssl.create_default_context()
        _ssl_ctx.check_hostname = False
        _ssl_ctx.verify_mode = ssl.CERT_NONE
        await aiosmtplib.send(
            msg,
            hostname=_smtp_host,
            port=_smtp_port,
            username=_smtp_user,
            password=_smtp_pass,
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


async def poll_imap_account(creds: dict, handle_reply_callback) -> None:
    """
    Poll one IMAP account for unseen messages and call handle_reply_callback for each.
    creds keys: host, port, user, pass, folder, poll_interval
    Never raises — exceptions are caught and logged.
    """
    host = creds["host"]
    port = creds["port"]
    user = creds["user"]
    password = creds["pass"]
    folder = creds.get("folder", "INBOX")

    try:
        _imap_ssl = ssl.create_default_context()
        _imap_ssl.check_hostname = False
        _imap_ssl.verify_mode = ssl.CERT_NONE
        imap = aioimaplib.IMAP4_SSL(host=host, port=port, ssl_context=_imap_ssl)
        await imap.wait_hello_from_server()
        await imap.login(user, password)
        await imap.select(folder)

        # Try narrow search first — only fetch actual replies (have In-Reply-To header)
        try:
            _, data = await imap.search('UNSEEN HEADER "In-Reply-To" ""')
            uid_list = data[0].split() if data and data[0] else []
        except Exception:
            # Fallback: all UNSEEN (some IMAP servers don't support HEADER search)
            _, data = await imap.search("UNSEEN")
            uid_list = data[0].split() if data and data[0] else []

        logger.info("[IMAP] Checked %s (%s) — %d unseen message(s)", host, user, len(uid_list))

        for uid in uid_list:
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            try:
                _, msg_data = await imap.fetch(uid_str, "(RFC822)")
                raw = None
                for part in msg_data:
                    if isinstance(part, (bytes, bytearray)) and len(part) > 100:
                        raw = bytes(part)
                        break
                if not raw:
                    logger.warning("[IMAP] No raw data for seq %s on %s — skipping", uid_str, host)
                    continue

                parser = email.parser.BytesParser(policy=email.policy.default)
                parsed = parser.parsebytes(raw)

                from_field = parsed.get("From", "")
                from_email_addr = email.utils.parseaddr(from_field)[1].strip().lower()
                subject = parsed.get("Subject", "")
                msg_id = parsed.get("Message-ID", "").strip()
                in_reply_to = parsed.get("In-Reply-To", "").strip()
                references = parsed.get("References", "").strip()

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
                    "from_email": from_email_addr,
                    "subject": subject,
                    "body": body.strip() if body else "",
                    "message_id": msg_id,
                    "in_reply_to": in_reply_to,
                    "references": references,
                }

                matched = await handle_reply_callback(reply_data)
                if matched:
                    await imap.store(uid_str, "+FLAGS", "\\Seen")
                    logger.info("[IMAP] Processed and marked Seen: seq=%s from=%s on %s", uid_str, from_email_addr, host)
                else:
                    logger.info("[IMAP] No campaign match — leaving unseen: seq=%s from=%s on %s", uid_str, from_email_addr, host)

            except Exception as e:
                logger.error("[IMAP] Error processing uid %s on %s: %s", uid_str, host, e)

        await imap.logout()

    except Exception as e:
        logger.error("[IMAP] Poll cycle error on %s (%s) at %s: %s", host, user, datetime.now(timezone.utc).isoformat(), e)


async def poll_imap_replies(handle_reply_callback) -> None:
    """
    Long-running asyncio loop that polls the global IMAP account for unseen messages.
    Calls handle_reply_callback(reply_data) for each new message.
    Never crashes — exceptions are caught, logged, and the loop continues.
    """
    logger.info("[IMAP] Polling loop started (interval: %ds)", settings.IMAP_POLL_INTERVAL_SECONDS)

    while True:
        await poll_imap_account(
            creds={
                "host": settings.IMAP_HOST,
                "port": settings.IMAP_PORT,
                "user": settings.IMAP_USER,
                "pass": settings.IMAP_PASS,
                "folder": settings.IMAP_REPLY_FOLDER,
            },
            handle_reply_callback=handle_reply_callback,
        )
        await asyncio.sleep(settings.IMAP_POLL_INTERVAL_SECONDS)
