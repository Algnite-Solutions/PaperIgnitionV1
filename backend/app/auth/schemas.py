from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None

class UserCreate(UserBase):
    username: str
    email: EmailStr
    password: str

class UserCreateEmail(BaseModel):
    email: EmailStr
    password: str
    username: str

class UserLoginEmail(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    identifier: Optional[str] = None

class ActivityData(BaseModel):
    """User activity statistics"""
    favorite_count: int = 0
    viewed_count: int = 0
    days_active: int = 0

class UserOut(UserBase):
    id: int
    is_active: Optional[bool] = True
    research_interests_text: Optional[str] = None
    rewrite_interest: Optional[str] = None
    profile_json: Optional[Dict[str, Any]] = None
    blog_language: Optional[str] = None
    username: str
    email: EmailStr
    research_domain_ids: Optional[List[int]] = None
    activity_data: Optional[ActivityData] = None

    class Config:
        from_attributes = True

class UserInfo(BaseModel):
    email: EmailStr
    username: str

class EmailLoginResponse(Token):
    needs_interest_setup: bool = Field(False, description="Indicates if the user needs to set up their research interests.")
    user_info: UserInfo

class UserProfileUpdate(BaseModel):
    email: Optional[EmailStr] = None
    push_frequency: Optional[str] = None
    research_interests_text: Optional[str] = None
    research_domain_ids: Optional[List[int]] = None
    profile_json: Optional[Dict[str, Any]] = None
    blog_language: Optional[str] = None
