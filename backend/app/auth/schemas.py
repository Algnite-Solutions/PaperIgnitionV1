from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, EmailStr, Field, field_validator


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

class BoosterStatus(BaseModel):
    """Customization Booster status"""
    new_likes_count: int = 0
    eligible: bool = False      # new_likes_count >= 5
    requested: bool = False     # user has clicked the booster button
    pool_size: int = 0          # number of candidates in profile pool
    best_f1: Optional[float] = None  # best F1 score across pool candidates

class UserOut(UserBase):
    id: int
    is_active: Optional[bool] = True
    is_verified: Optional[bool] = False
    research_interests_text: Optional[str] = None
    rewrite_interest: Optional[str] = None
    profile_json: Optional[Dict[str, Any]] = None
    blog_language: Optional[str] = None
    username: str
    email: EmailStr
    research_domain_ids: Optional[List[int]] = None
    activity_data: Optional[ActivityData] = None
    booster_status: Optional[BoosterStatus] = None
    profile_last_extracted_at: Optional[str] = None
    profile_pool_version: Optional[int] = None
    profile_boost_requested: Optional[bool] = None

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


class ProfilePoolEntryIn(BaseModel):
    """Input schema for saving a pool entry (from orchestrator)."""
    profile_json: Dict[str, Any]
    generation: int = 0
    parent_id: Optional[Union[str, int]] = None
    mutation_note: Optional[str] = None
    is_active: bool = False
    precision_val: Optional[float] = None
    recall_val: Optional[float] = None
    f1_val: Optional[float] = None
    val_days_count: int = 0
    breakdown_str: Optional[str] = None

    @field_validator("parent_id", mode="before")
    @classmethod
    def coerce_parent_id(cls, v):
        if v is not None:
            return str(v)
        return None


class ProfilePoolEntryOut(BaseModel):
    """Output schema for reading a pool entry."""
    id: int
    profile_json: Dict[str, Any]
    precision_val: Optional[float] = None
    recall_val: Optional[float] = None
    f1_val: Optional[float] = None
    val_days_count: int = 0
    generation: int = 0
    parent_id: Optional[str] = None
    mutation_note: Optional[str] = None
    breakdown_str: Optional[str] = None
    is_active: bool = False
    created_at: Optional[str] = None
    evaluated_at: Optional[str] = None

    class Config:
        from_attributes = True


class SaveProfilePoolRequest(BaseModel):
    """Request body for saving the full profile pool."""
    entries: List[ProfilePoolEntryIn]
    active_entry_index: int  # index into entries list that should be active


class BoostHistoryIn(BaseModel):
    """Request body for recording a boost event."""
    boost_number: int
    cumulative_likes: int
    pool_version: int
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    active_profile_json: Optional[Dict[str, Any]] = None
    changes_made: Optional[str] = None
    pool_candidates_count: int = 0
    pool_diversity: Optional[List[Dict[str, Any]]] = None
