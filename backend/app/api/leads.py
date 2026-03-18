import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.lead import Lead
from app.models.outreach_account import OutreachAccount
from app.models.user import User
from app.models.website_scan import WebsiteScan
from app.schemas.lead import (
    AccountAssignmentItem,
    ImportResponse,
    LeadAccountAssignment,
    LeadListResponse,
    LeadResponse,
    LeadStatsResponse,
    LeadUpdate,
    PaginatedLeadsResponse,
    WebsiteScanResponse,
)

router = APIRouter(prefix="/leads", tags=["leads"])

VALID_EMAIL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@._+-")


def is_valid_email(email: str) -> bool:
    email = email.strip()
    if not email or "@" not in email:
        return False
    parts = email.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1] or "." not in parts[1]:
        return False
    return True


@router.post("/import", response_model=ImportResponse)
async def import_leads(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    imported = 0
    skipped = 0
    errors = []

    rows_to_insert = []
    seen_emails = set()

    for i, row in enumerate(reader, start=2):  # start=2 because row 1 is header
        email = row.get("email", "").strip().lower()
        if not email:
            errors.append(f"Row {i}: missing email")
            continue
        if not is_valid_email(email):
            errors.append(f"Row {i}: invalid email '{email}'")
            continue
        if email in seen_emails:
            skipped += 1
            continue
        seen_emails.add(email)
        rows_to_insert.append({
            "email": email,
            "first_name": row.get("first_name", "").strip() or None,
            "last_name": row.get("last_name", "").strip() or None,
            "company": row.get("company", "").strip() or None,
            "title": row.get("title", "").strip() or None,
            "website": row.get("website", "").strip() or None,
            "industry": row.get("industry", "").strip() or None,
            "company_size": row.get("company_size", "").strip() or None,
        })

    if rows_to_insert:
        emails_to_check = [r["email"] for r in rows_to_insert]
        existing_result = await db.execute(
            select(Lead.email).where(Lead.email.in_(emails_to_check))
        )
        existing_emails = set(existing_result.scalars().all())
    else:
        existing_emails = set()

    for row_data in rows_to_insert:
        if row_data["email"] in existing_emails:
            skipped += 1
            continue
        lead = Lead(**row_data)
        db.add(lead)
        imported += 1

    await db.flush()
    return ImportResponse(imported=imported, skipped=skipped, errors=errors)


@router.get("/stats", response_model=LeadStatsResponse)
async def get_lead_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    )
    rows = result.all()
    return LeadStatsResponse(status_counts={row[0]: row[1] for row in rows})


@router.get("", response_model=PaginatedLeadsResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Lead)
    if status:
        query = query.where(Lead.status == status)
    if min_score is not None:
        query = query.where(Lead.score >= min_score)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.order_by(Lead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    leads = result.scalars().all()

    return PaginatedLeadsResponse(
        items=[LeadListResponse.model_validate(lead) for lead in leads],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(selectinload(Lead.messages), selectinload(Lead.conversations))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Lead not found", "code": "NOT_FOUND"},
        )
    return lead


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: str,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(selectinload(Lead.messages), selectinload(Lead.conversations))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Lead not found", "code": "NOT_FOUND"},
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)

    await db.flush()
    return lead


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Lead not found", "code": "NOT_FOUND"},
        )
    await db.delete(lead)
    await db.flush()


@router.post("/assign-accounts")
async def assign_accounts(
    body: LeadAccountAssignment,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Bulk assign outreach accounts to specific leads."""
    assigned = 0
    for item in body.assignments:
        result = await db.execute(select(Lead).where(Lead.id == item.lead_id))
        lead = result.scalar_one_or_none()
        if lead:
            lead.outreach_account_id = item.outreach_account_id
            assigned += 1
    await db.flush()
    return {"assigned": assigned}


@router.post("/auto-assign")
async def auto_assign_accounts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Round-robin distribute unassigned leads across active accounts respecting daily_limit."""
    # Load active accounts that still have capacity
    accounts_result = await db.execute(
        select(OutreachAccount)
        .where(OutreachAccount.is_active.is_(True))
        .order_by(OutreachAccount.created_at)
    )
    accounts = [a for a in accounts_result.scalars().all() if a.leads_assigned < a.daily_limit]

    if not accounts:
        return {"assigned": 0, "skipped": 0}

    # Load unassigned scored leads
    leads_result = await db.execute(
        select(Lead).where(Lead.outreach_account_id.is_(None), Lead.status != "not_interested")
    )
    leads = list(leads_result.scalars().all())

    assigned = 0
    skipped = 0
    account_idx = 0

    for lead in leads:
        # Advance to next account with remaining capacity
        while account_idx < len(accounts) and accounts[account_idx].leads_assigned >= accounts[account_idx].daily_limit:
            account_idx += 1

        if account_idx >= len(accounts):
            skipped += 1
            continue

        acc = accounts[account_idx]
        lead.outreach_account_id = acc.id
        acc.leads_assigned += 1
        assigned += 1

        # Move to next account (round-robin)
        account_idx = (account_idx + 1) % len(accounts)

    await db.flush()
    return {"assigned": assigned, "skipped": skipped}


@router.get("/{lead_id}/scan", response_model=WebsiteScanResponse)
async def get_lead_scan(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return the website scan result for a lead."""
    result = await db.execute(
        select(WebsiteScan).where(WebsiteScan.lead_id == lead_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "No scan found for this lead", "code": "NOT_FOUND"},
        )
    return ws


@router.post("/{lead_id}/scan")
async def trigger_lead_scan(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Queue a (re-)scan for a lead's website."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Lead not found", "code": "NOT_FOUND"},
        )
    lead.scan_status = "pending"
    lead.scan_retry_count = 0
    await db.flush()
    return {"status": "scan_queued"}
