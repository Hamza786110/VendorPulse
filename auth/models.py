 # Pydantic schemas
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str | None = None

class UserSignin(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"