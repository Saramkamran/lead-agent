import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.jobs.scheduler import job_score_new_leads, job_send_daily_outreach, job_send_followups
from app.models.email_log import EmailLog
from app.models.lead import Lead
from app.services.conversation_service import classify_intent
from app.services.reply_handler import handle_reply

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/score")
async def trigger_score(_=Depends(get_current_user)):
    await job_score_new_leads()
    return {"ok": True, "job": "score_new_leads"}


@router.post("/outreach")
async def trigger_outreach(_=Depends(get_current_user)):
    sent = await job_send_daily_outreach(bypass_hour_check=True)
    return {"ok": True, "job": "send_daily_outreach", "sent": sent}


@router.post("/followups")
async def trigger_followups(_=Depends(get_current_user)):
    await job_send_followups()
    return {"ok": True, "job": "send_followups"}


@router.get("/test-openai")
async def test_openai(_=Depends(get_current_user)):
    try:
        result = await classify_intent("I am interested in learning more, please send me details.")
        return {"ok": True, "model": "gpt-4o-mini", "response": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class BackfillLogRequest(BaseModel):
    lead_email: str
    message_id: str
    subject: str = ""


@router.post("/backfill-outbound-log")
async def backfill_outbound_log(
    body: BackfillLogRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(Lead).where(Lead.email == body.lead_email.lower()))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail={"error": "Lead not found", "code": "NOT_FOUND"})

    db.add(EmailLog(
        id=str(uuid.uuid4()),
        lead_id=lead.id,
        direction="outbound",
        message_id=body.message_id,
        subject=body.subject,
        body="",
        received_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return {"ok": True, "lead_id": lead.id, "message_id": body.message_id}


class ProcessReplyRequest(BaseModel):
    from_email: str
    subject: str
    body: str
    message_id: str = ""
    in_reply_to: str = ""
    references: str = ""


@router.post("/process-reply")
async def process_reply(
    body: ProcessReplyRequest,
    _=Depends(get_current_user),
):
    await handle_reply({
        "from_email": body.from_email,
        "subject": body.subject,
        "body": body.body,
        "message_id": body.message_id,
        "in_reply_to": body.in_reply_to,
        "references": body.references,
    })
    return {"ok": True}
