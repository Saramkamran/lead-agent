from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, hash_password, verify_password
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_REGULAR_USERS = 3  # Total non-admin users allowed


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Email already registered", "code": "EMAIL_EXISTS"},
        )

    # Count existing users to determine role
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar() or 0

    if user_count == 0:
        # First user ever — becomes admin
        role = "admin"
    else:
        # Check regular user limit (non-admin count)
        non_admin_result = await db.execute(
            select(func.count(User.id)).where(User.role != "admin")
        )
        non_admin_count = non_admin_result.scalar() or 0
        if non_admin_count >= MAX_REGULAR_USERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "User limit reached (max 3 regular users)", "code": "USER_LIMIT_REACHED"},
            )
        role = "user"

    user = User(
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
        role=role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid credentials", "code": "INVALID_CREDENTIALS"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Account is deactivated", "code": "ACCOUNT_INACTIVE"},
        )

    token = create_access_token({"sub": user.id, "role": user.role})
    return TokenResponse(access_token=token)
