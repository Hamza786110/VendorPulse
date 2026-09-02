 # /auth/signup, /auth/signin
from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timezone
from auth.models import UserSignup, UserSignin, Token
from auth.utils import hash_password, verify_password, create_access_token
from auth.dependencies import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

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