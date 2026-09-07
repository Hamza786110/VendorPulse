 # /auth/signup, /auth/signin
from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timezone,timedelta
from auth.models import (
    UserSignup,
    UserSignin,
    Token,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    PasswordResetToken,
)
from auth.utils import (
    hash_password,
    verify_password,
    create_access_token,
    generate_reset_token,
    hash_reset_token,
)
from auth.email_utils import send_password_reset_email
from auth.dependencies import get_current_user, get_db

router = APIRouter(prefix="/auth", tags=["auth"])
RESET_TOKEN_EXPIRE_MINUTES = 30
@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
async def signup(user: UserSignup, db=Depends(get_db)):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_doc = {
        "email": user.email,
        "hashed_password": hash_password(user.password),
        "full_name": user.full_name,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(user_doc)
    token = create_access_token({"sub": str(result.inserted_id)})
    return Token(access_token=token)

@router.post("/signin", response_model=Token)
async def signin(user: UserSignin, db=Depends(get_db)):
    db_user = await db.users.find_one({"email": user.email})
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": str(db_user["_id"])})
    return Token(access_token=token)

@router.get("/me")
async def read_current_user(current_user=Depends(get_current_user)):
    return {
        "id": str(current_user["_id"]),
        "email": current_user["email"],
        "full_name": current_user.get("full_name"),
    }
@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(payload: ForgotPasswordRequest, db=Depends(get_db)):
    user = await db.users.find_one({"email": payload.email})

    generic_response = ForgotPasswordResponse(
        message="If that email is registered, a password reset link has been sent."
    )

    if not user:
        return generic_response

    raw_token = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    reset_record = PasswordResetToken(
        user_id=str(user["_id"]),
        hashed_token=hash_reset_token(raw_token),
        expires_at=expires_at,
    )

    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "reset_token_hash": reset_record.hashed_token,
            "reset_token_expires": reset_record.expires_at,
        }},
    )

    try:
        send_password_reset_email(to_email=payload.email, raw_token=raw_token)
    except Exception as e:
        print(f"[ERROR] Failed to send password reset email to {payload.email}: {e}")

    return generic_response

@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db=Depends(get_db)):
    token_hash = hash_reset_token(payload.token)
    user = await db.users.find_one({"reset_token_hash": token_hash})

    invalid_token_exception = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired reset token",
    )

    if not user:
        raise invalid_token_exception

    expires_at = user.get("reset_token_expires")
    if expires_at is None:
        raise invalid_token_exception

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > expires_at:
        raise invalid_token_exception

    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {"hashed_password": hash_password(payload.new_password)},
            "$unset": {"reset_token_hash": "", "reset_token_expires": ""},
        },
    )

    return {"message": "Password has been reset successfully"}