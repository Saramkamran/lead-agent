import csv
import io
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from openai import AsyncOpenAI
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.lead import Lead
from app.models.message import Message
from app.models.outreach_account import OutreachAccount
from app.models.user import User
from app.models.website_scan import WebsiteScan

logger = logging.getLogger(__name__)
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

_SCHEMA_FIELDS = ["email", "first_name", "last_name", "full_name", "company", "title", "website", "industry", "company_size"]


async def _ai_map_columns(headers: list[str], sample_row: dict) -> dict[str, str]:
    """
    Use GPT-4o-mini to map arbitrary CSV column names to CRM schema fields.
    Returns a dict like {"Email Address": "email", "Business Name": "company"}.
    Falls back to empty dict on any error.
    """
    if not settings.OPENAI_API_KEY:
        return {}
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        prompt = (
            f"Map these CSV column headers to CRM field names.\n"
            f"CRM fields: {', '.join(_SCHEMA_FIELDS)}\n"
            f"CSV headers: {headers}\n"
            f"Sample row: {json.dumps(sample_row)}\n\n"
            "Return a JSON object mapping each CSV header to the best CRM field name, "
            "or null if there is no match. Example: {{\"Email Address\": \"email\", \"Business\": \"company\"}}\n"
            "Return valid JSON only."
        )
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        mapping = json.loads(raw)
        # Filter to only valid schema field targets
        return {k: v for k, v in mapping.items() if v in _SCHEMA_FIELDS}
    except Exception as e:
        logger.warning("[CSV] AI column mapping failed: %s", e)
        return {}


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

    raw_reader = csv.DictReader(io.StringIO(text))

    # Read all rows to get headers + sample row for AI mapping
    all_raw_rows = list(raw_reader)
    if not all_raw_rows:
        return ImportResponse(imported=0, skipped=0, errors=["CSV file is empty"])

    headers = list(all_raw_rows[0].keys())
    sample_row = {k: v for k, v in all_raw_rows[0].items()}

    # Try AI column mapping first
    ai_mapping = await _ai_map_columns(headers, sample_row)

    # Static alias fallback
    _ALIASES: dict[str, str] = {
        # email
        "e-mail": "email", "e_mail": "email", "email address": "email",
        # name
        "contact name": "full_name", "name": "full_name",
        "contact": "full_name", "full name": "full_name", "contact person": "full_name",
        "person": "full_name", "rep": "full_name", "representative": "full_name",
        "firstname": "first_name", "first": "first_name",
        "lastname": "last_name", "last": "last_name", "surname": "last_name",
        # company
        "organization": "company", "organisation": "company", "account": "company",
        "business": "company", "business name": "company", "company name": "company",
        # website / domain
        "domain": "website", "url": "website", "web": "website",
        "website url": "website", "domain name": "website", "web address": "website",
        "web url": "website", "site": "website", "site url": "website",
        # size
        "employee count": "company_size", "employees": "company_size",
        "num employees": "company_size", "# employees": "company_size",
        "headcount": "company_size", "company size": "company_size",
        # industry
        "sector": "industry", "vertical": "industry",
    }

    def _norm(row: dict) -> dict:
        out: dict = {}
        for k, v in row.items():
            # AI mapping takes precedence over static aliases
            ai_target = ai_mapping.get(k)
            if ai_target:
                key = ai_target
            else:
                key = k.strip().lower()
                key = _ALIASES.get(key, key)
            out[key] = v
        # Split "full_name" into first/last if dedicated columns absent
        if "full_name" in out and "first_name" not in out:
            parts = out.pop("full_name", "").strip().split(None, 1)
            out["first_name"] = parts[0] if parts else ""
            out["last_name"] = parts[1] if len(parts) > 1 else ""
        return out

    imported = 0
    skipped = 0
    errors = []

    rows_to_insert = []
    seen_emails = set()

    for i, raw_row in enumerate(all_raw_rows, start=2):  # start=2 because row 1 is header
        row = _norm(raw_row)
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
    max_score: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Lead)
    if status:
        query = query.where(Lead.status == status)
    if min_score is not None:
        query = query.where(Lead.score >= min_score)
    if max_score is not None:
        query = query.where(Lead.score <= max_score)

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

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Invalid outreach_account_id — account not found", "code": "INVALID_ACCOUNT"},
        )
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


class BulkIdsRequest(BaseModel):
    ids: list[str]


@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_leads(
    body: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Lead).where(Lead.id.in_(body.ids)))
    leads = result.scalars().all()
    for lead in leads:
        await db.delete(lead)
    await db.commit()
    return {"deleted": len(leads)}


@router.post("/bulk-score", status_code=status.HTTP_200_OK)
async def bulk_score_leads(
    body: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.services.scoring_service import score_lead
    from app.services.offer_service import generate_offer

    result = await db.execute(select(Lead).where(Lead.id.in_(body.ids)))
    leads = result.scalars().all()
    scored = 0
    for lead in leads:
        try:
            s, reason = await score_lead(lead, db=db)
            lead.score = s
            lead.score_reason = reason
            offer = await generate_offer(lead, db)
            lead.custom_offer = offer
            if lead.status == "imported":
                lead.status = "scored"
            scored += 1
        except Exception as e:
            logger.warning("Bulk score failed for lead %s: %s", lead.id, e)
    await db.commit()
    return {"scored": scored}


@router.post("/bulk-process", status_code=status.HTTP_200_OK)
async def bulk_process_leads(
    body: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.services.scan_service import scan_website
    from app.services.scoring_service import score_lead
    from app.services.offer_service import generate_offer
    from app.services.message_service import generate_messages

    result = await db.execute(select(Lead).where(Lead.id.in_(body.ids)))
    leads = result.scalars().all()
    processed = 0
    for lead in leads:
        try:
            if lead.website and lead.scan_status in ("pending", "failed", None):
                lead.scan_status = "scanning"
                await db.flush()
                ws = await scan_website(lead, db)
                lead.scan_status = "success" if ws else "failed"
            if lead.score is None:
                s, reason = await score_lead(lead, db=db)
                lead.score = s
                lead.score_reason = reason
                offer = await generate_offer(lead, db)
                lead.custom_offer = offer
            lead.status = "scored"
            await generate_messages(lead=lead, db=db)
            await db.commit()
            processed += 1
        except Exception as e:
            logger.warning("Bulk process failed for lead %s: %s", lead.id, e)
            await db.rollback()
    return {"processed": processed}


@router.delete("/{lead_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_messages(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Delete cached messages for a lead so they will be regenerated on the next process/outreach run.
    Blocked for leads in an active outreach sequence to prevent the followup job from crashing.
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Lead not found", "code": "NOT_FOUND"},
        )
    if lead.status in ("contacted", "follow_up_1", "follow_up_2", "follow_up_3"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Cannot delete messages for a lead in an active outreach sequence. "
                         "Wait for the sequence to complete or mark the lead as not_interested first.",
                "code": "LEAD_IN_SEQUENCE",
            },
        )
    await db.execute(sql_delete(Message).where(Message.lead_id == lead_id))
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


@router.post("/{lead_id}/process", response_model=LeadResponse)
async def process_lead(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Run full pipeline for one lead: scan → score → offer → generate messages."""
    from app.services.scan_service import scan_website
    from app.services.scoring_service import score_lead
    from app.services.offer_service import generate_offer
    from app.services.message_service import generate_messages

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

    # Step 1: Website scan
    if lead.website:
        lead.scan_status = "scanning"
        await db.flush()
        ws = await scan_website(lead, db)
        lead.scan_status = "success" if ws else "failed"
    else:
        lead.scan_status = "failed"

    # Step 2: Score + offer
    score, reason = await score_lead(lead)
    lead.score = score
    lead.score_reason = reason
    offer = await generate_offer(lead, db)
    lead.custom_offer = offer
    lead.status = "scored"

    # Step 3: Generate messages (skips if messages already exist for this lead)
    await generate_messages(lead=lead, db=db)

    await db.commit()

    result2 = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(selectinload(Lead.messages), selectinload(Lead.conversations))
    )
    return result2.scalar_one()


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
