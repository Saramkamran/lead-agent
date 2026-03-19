import asyncio
import logging
import ssl

import aiosmtplib
import aioimaplib
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.database import get_db
from app.models.lead import Lead
from app.models.outreach_account import OutreachAccount
from app.models.user import User
from app.schemas.outreach_account import OutreachAccountCreate, OutreachAccountOut, OutreachAccountUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outreach-accounts", tags=["outreach-accounts"])

MAX_ACCOUNTS = 5


@router.post("", response_model=OutreachAccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: OutreachAccountCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    count_result = await db.execute(select(OutreachAccount))
    existing = list(count_result.scalars().all())
    if len(existing) >= MAX_ACCOUNTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Maximum of {MAX_ACCOUNTS} outreach accounts allowed", "code": "MAX_ACCOUNTS_REACHED"},
        )

    account = OutreachAccount(
        display_name=body.display_name,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_user=body.smtp_user,
        smtp_pass=encrypt_secret(body.smtp_pass),
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        from_name=body.from_name,
        from_email=body.from_email,
        daily_limit=body.daily_limit,
    )
    db.add(account)
    await db.flush()
    return account


@router.get("", response_model=list[OutreachAccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OutreachAccount).order_by(OutreachAccount.created_at))
    return list(result.scalars().all())


@router.get("/{account_id}", response_model=OutreachAccountOut)
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OutreachAccount).where(OutreachAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Outreach account not found", "code": "NOT_FOUND"},
        )
    return account


@router.patch("/{account_id}", response_model=OutreachAccountOut)
async def update_account(
    account_id: str,
    body: OutreachAccountUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OutreachAccount).where(OutreachAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Outreach account not found", "code": "NOT_FOUND"},
        )

    updates = body.model_dump(exclude_unset=True)
    if "smtp_pass" in updates and updates["smtp_pass"]:
        updates["smtp_pass"] = encrypt_secret(updates["smtp_pass"])
    for field, value in updates.items():
        setattr(account, field, value)

    await db.flush()
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OutreachAccount).where(OutreachAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Outreach account not found", "code": "NOT_FOUND"},
        )

    # Null out outreach_account_id on any leads using this account
    await db.execute(
        update(Lead)
        .where(Lead.outreach_account_id == account_id)
        .values(outreach_account_id=None)
    )
    await db.delete(account)
    await db.flush()


@router.post("/{account_id}/test-connection")
async def test_connection(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OutreachAccount).where(OutreachAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Outreach account not found", "code": "NOT_FOUND"},
        )

    try:
        plain_pass = decrypt_secret(account.smtp_pass)
    except Exception as e:
        return {"smtp": "failed", "imap": "failed", "error": f"Failed to decrypt password: {e}"}

    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE

    _CONN_TIMEOUT = 10.0  # seconds before giving up on unreachable hosts

    # Test SMTP
    smtp_status = "failed"
    smtp_error = ""
    try:
        async def _test_smtp() -> None:
            use_tls = account.smtp_port == 465
            smtp = aiosmtplib.SMTP(
                hostname=account.smtp_host,
                port=account.smtp_port,
                use_tls=use_tls,
                tls_context=_ssl_ctx,
            )
            await smtp.connect()
            if not use_tls:
                await smtp.starttls(tls_context=_ssl_ctx)
            await smtp.login(account.smtp_user, plain_pass)
            await smtp.quit()

        await asyncio.wait_for(_test_smtp(), timeout=_CONN_TIMEOUT)
        smtp_status = "ok"
    except asyncio.TimeoutError:
        smtp_error = f"Connection timed out after {int(_CONN_TIMEOUT)}s — check host/port"
        logger.warning("[TEST] SMTP timed out for account %s", account_id)
    except Exception as e:
        smtp_error = str(e)
        logger.warning("[TEST] SMTP failed for account %s: %s", account_id, e)

    # Test IMAP
    imap_status = "failed"
    imap_error = ""
    try:
        async def _test_imap() -> None:
            imap = aioimaplib.IMAP4_SSL(
                host=account.imap_host, port=account.imap_port, ssl_context=_ssl_ctx
            )
            await imap.wait_hello_from_server()
            await imap.login(account.smtp_user, plain_pass)
            await imap.logout()

        await asyncio.wait_for(_test_imap(), timeout=_CONN_TIMEOUT)
        imap_status = "ok"
    except asyncio.TimeoutError:
        imap_error = f"Connection timed out after {int(_CONN_TIMEOUT)}s — check host/port"
        logger.warning("[TEST] IMAP timed out for account %s", account_id)
    except Exception as e:
        imap_error = str(e)
        logger.warning("[TEST] IMAP failed for account %s: %s", account_id, e)

    error_msg = "; ".join(filter(None, [smtp_error, imap_error]))
    return {"smtp": smtp_status, "imap": imap_status, "error": error_msg or None}
