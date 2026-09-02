# get_current_user
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from auth.utils import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/signin")

def get_db(request: Request):
    return request.app.state.db

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db=Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise credentials_exception

    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if user is None:
        raise credentials_exception
    return user