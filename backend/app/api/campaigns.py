from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.user import User
from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def _campaign_with_lead_count(campaign: Campaign, db: AsyncSession) -> CampaignResponse:
    count_result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.score >= campaign.min_score,
            Lead.status == "scored",
        )
    )
    lead_count = count_result.scalar_one() or 0
    data = CampaignResponse.model_validate(campaign)
    data.lead_count = lead_count
    return data


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    campaign = Campaign(**body.model_dump())
    db.add(campaign)
    await db.flush()
    await db.refresh(campaign)
    return await _campaign_with_lead_count(campaign, db)


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    campaigns = result.scalars().all()
    return [await _campaign_with_lead_count(c, db) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Campaign not found", "code": "NOT_FOUND"},
        )
    return await _campaign_with_lead_count(campaign, db)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Campaign not found", "code": "NOT_FOUND"},
        )
    if campaign.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Cannot edit an active campaign", "code": "CAMPAIGN_ACTIVE"},
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(campaign, field, value)

    await db.flush()
    await db.refresh(campaign)
    return await _campaign_with_lead_count(campaign, db)


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
async def start_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Campaign not found", "code": "NOT_FOUND"},
        )
    if not campaign.sender_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "sender_email is required to start a campaign", "code": "MISSING_SENDER_EMAIL"},
        )
    if not campaign.calendly_link:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "calendly_link is required to start a campaign", "code": "MISSING_CALENDLY_LINK"},
        )

    campaign.status = "active"
    await db.flush()
    return await _campaign_with_lead_count(campaign, db)


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Campaign not found", "code": "NOT_FOUND"},
        )

    campaign.status = "paused"
    await db.flush()
    return await _campaign_with_lead_count(campaign, db)
