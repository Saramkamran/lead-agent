from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.jobs.scheduler import job_score_new_leads, job_send_daily_outreach, job_send_followups

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/score")
async def trigger_score(_=Depends(get_current_user)):
    await job_score_new_leads()
    return {"ok": True, "job": "score_new_leads"}


@router.post("/outreach")
async def trigger_outreach(_=Depends(get_current_user)):
    await job_send_daily_outreach()
    return {"ok": True, "job": "send_daily_outreach"}


@router.post("/followups")
async def trigger_followups(_=Depends(get_current_user)):
    await job_send_followups()
    return {"ok": True, "job": "send_followups"}
