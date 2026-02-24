from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


AccessLevel = Literal["section", "central"]


class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8, max_length=1024)
    client_fingerprint: Optional[str] = Field(default=None, max_length=256)


class AuthRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=32, max_length=4096)
    client_fingerprint: Optional[str] = Field(default=None, max_length=256)


class AuthLogoutRequest(BaseModel):
    refresh_token: Optional[str] = Field(default=None, max_length=4096)


class AuthPasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=1024)
    new_password: str = Field(..., min_length=12, max_length=1024)


class AuthAdminPasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=12, max_length=1024)
    revoke_existing_sessions: bool = True


class AuthUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=200)
    password: str = Field(..., min_length=12, max_length=1024)
    role: str = Field(default="analyst", min_length=1, max_length=64)
    access_level: AccessLevel = "section"
    section_code: Optional[str] = Field(default=None, max_length=64)
    scopes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_section_rules(self) -> "AuthUserCreateRequest":
        if self.access_level == "section" and not (self.section_code or "").strip():
            raise ValueError("section_code_required_for_section_access")
        return self


class AuthTokenPairResponse(BaseModel):
    token_type: str = "bearer"
    access_token: str
    refresh_token: str
    access_expires_at: str
    refresh_expires_at: str
    principal: Dict[str, Any]


class AuthUserOut(BaseModel):
    user_id: str
    username: str
    display_name: Optional[str] = None
    role: str
    access_level: AccessLevel
    section_code: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    is_active: bool
    failed_login_count: int
    locked_until: Optional[str] = None
    created_at: str
    updated_at: str


class AuthUsersListResponse(BaseModel):
    total: int
    items: List[AuthUserOut] = Field(default_factory=list)
