import ssl
import uuid

import aiosmtplib
import aioimaplib
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin, hash_password
from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.core.database import get_db
from app.models.outreach_account import OutreachAccount
from app.models.user import User
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])


# ── User management ──────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    email: str
    password: str


class UpdateUserRequest(BaseModel):
    is_active: bool


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    from sqlalchemy import func
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Email already registered", "code": "EMAIL_EXISTS"},
        )
    non_admin_result = await db.execute(
        select(func.count(User.id)).where(User.role != "admin")
    )
    non_admin_count = non_admin_result.scalar() or 0
    if non_admin_count >= 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "User limit reached (max 3 regular users)", "code": "USER_LIMIT_REACHED"},
        )
    user = User(
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
        role="user",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def toggle_user(
    user_id: str,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Cannot deactivate your own account", "code": "SELF_ACTION"},
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "User not found", "code": "NOT_FOUND"})
    if user.role == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error": "Cannot modify another admin", "code": "FORBIDDEN"})
    user.is_active = body.is_active
    await db.flush()
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Cannot delete your own account", "code": "SELF_ACTION"},
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "User not found", "code": "NOT_FOUND"})
    if user.role == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error": "Cannot delete an admin account", "code": "FORBIDDEN"})
    await db.delete(user)
    await db.flush()


# ── Smoke test ───────────────────────────────────────────────────────────────

@router.post("/smoke-test")
async def smoke_test(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Run post-deploy health checks and return pass/fail for each."""
    results = []

    # 1. DB connection check
    try:
        await db.execute(select(User).limit(1))
        results.append({"check": "db_connection", "passed": True})
    except Exception as e:
        results.append({"check": "db_connection", "passed": False, "error": str(e)})

    # 2 & 3. SMTP + IMAP per active account
    acc_result = await db.execute(select(OutreachAccount).where(OutreachAccount.is_active.is_(True)))
    accounts = list(acc_result.scalars().all())

    for account in accounts:
        name = account.display_name or account.smtp_user
        try:
            plain_pass = decrypt_secret(account.smtp_pass)
        except Exception as e:
            results.append({"check": f"smtp_{name}", "passed": False, "error": f"decrypt: {e}"})
            results.append({"check": f"imap_{name}", "passed": False, "error": f"decrypt: {e}"})
            continue

        # SMTP
        try:
            use_tls = account.smtp_port == 465
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            smtp = aiosmtplib.SMTP(
                hostname=account.smtp_host, port=account.smtp_port,
                use_tls=use_tls, tls_context=ssl_ctx,
            )
            await smtp.connect()
            if not use_tls:
                await smtp.starttls(tls_context=ssl_ctx)
            await smtp.login(account.smtp_user, plain_pass)
            await smtp.quit()
            results.append({"check": f"smtp_{name}", "passed": True})
        except Exception as e:
            results.append({"check": f"smtp_{name}", "passed": False, "error": str(e)})

        # IMAP
        try:
            imap_ssl = ssl.create_default_context()
            imap_ssl.check_hostname = False
            imap_ssl.verify_mode = ssl.CERT_NONE
            imap = aioimaplib.IMAP4_SSL(
                host=account.imap_host, port=account.imap_port, ssl_context=imap_ssl
            )
            await imap.wait_hello_from_server()
            await imap.login(account.smtp_user, plain_pass)
            await imap.logout()
            results.append({"check": f"imap_{name}", "passed": True})
        except Exception as e:
            results.append({"check": f"imap_{name}", "passed": False, "error": str(e)})

    # 4. At least 1 active campaign
    from app.models.campaign import Campaign
    from sqlalchemy import func
    camp_result = await db.execute(
        select(func.count(Campaign.id)).where(Campaign.status == "active")
    )
    active_campaigns = camp_result.scalar() or 0
    results.append({
        "check": "active_campaign",
        "passed": active_campaigns > 0,
        "detail": f"{active_campaigns} active campaign(s)",
    })

    # 5. API keys set
    results.append({"check": "anthropic_api_key", "passed": bool(settings.ANTHROPIC_API_KEY)})
    results.append({"check": "openai_api_key", "passed": bool(settings.OPENAI_API_KEY)})

    # 6. No leads stuck in scan_status='scanning' > 10 min
    from app.models.lead import Lead
    from datetime import datetime, timedelta, timezone
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    stale_result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.scan_status == "scanning",
            Lead.created_at <= stale_cutoff,
        )
    )
    stale_count = stale_result.scalar() or 0
    results.append({
        "check": "no_stale_scans",
        "passed": stale_count == 0,
        "detail": f"{stale_count} stale scan(s)",
    })

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    return {"passed": passed, "failed": failed, "results": results}
