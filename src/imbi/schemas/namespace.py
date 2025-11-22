"""
Pydantic schemas for Namespace endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NamespaceBase(BaseModel):
    """Base namespace schema with common fields."""

    namespace_id: int = Field(..., description="Unique namespace identifier")
    name: str = Field(..., min_length=1, max_length=255, description="Namespace name")
    slug: str = Field(..., min_length=1, max_length=255, description="URL-friendly slug")
    icon_class: Optional[str] = Field(None, description="CSS icon class (e.g., FontAwesome)")
    maintained_by: Optional[str] = Field(None, description="Team or person responsible")
    aws_ssm_slug: Optional[str] = Field(None, description="AWS Systems Manager parameter path prefix")


class NamespaceCreate(NamespaceBase):
    """Schema for creating a new namespace."""
    pass


class NamespaceUpdate(BaseModel):
    """Schema for updating an existing namespace (all fields optional)."""

    namespace_id: Optional[int] = Field(None, description="Unique namespace identifier")
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Namespace name")
    slug: Optional[str] = Field(None, min_length=1, max_length=255, description="URL-friendly slug")
    icon_class: Optional[str] = Field(None, description="CSS icon class")
    maintained_by: Optional[str] = Field(None, description="Team or person responsible")
    aws_ssm_slug: Optional[str] = Field(None, description="AWS Systems Manager parameter path")


class NamespaceResponse(NamespaceBase):
    """Schema for namespace responses (includes audit fields)."""

    id: int = Field(..., description="Internal database ID")
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {
        "from_attributes": True,  # Enable ORM mode
    }
