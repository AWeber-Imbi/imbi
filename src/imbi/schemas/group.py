"""
Pydantic schemas for Group endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GroupBase(BaseModel):
    """Base group schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Group name")
    permissions: list[str] = Field(default_factory=list, description="List of permissions")


class GroupCreate(GroupBase):
    """Schema for creating a new group."""
    pass


class GroupUpdate(BaseModel):
    """Schema for updating an existing group (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    permissions: Optional[list[str]] = None


class GroupResponse(GroupBase):
    """Schema for group responses (includes audit fields)."""

    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {
        "from_attributes": True,  # Enable ORM mode
    }


class GroupMemberAdd(BaseModel):
    """Schema for adding a member to a group."""

    username: str = Field(..., min_length=1, description="Username to add to group")


class GroupMemberResponse(BaseModel):
    """Schema for group member information."""

    username: str
    group: str
    added_by: str
    created_at: datetime

    model_config = {
        "from_attributes": True,
    }
