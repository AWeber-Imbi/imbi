"""
Pydantic schemas for Namespace endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class NamespaceBase(BaseModel):
    """Base namespace schema with common fields."""

    namespace_id: int = Field(..., description="Unique namespace identifier")
    name: str = Field(..., min_length=1, max_length=255, description="Namespace name")
    slug: str = Field(
        ..., min_length=1, max_length=255, description="URL-friendly slug"
    )
    icon_class: str | None = Field(
        None, description="CSS icon class (e.g., FontAwesome)"
    )
    maintained_by: str | None = Field(None, description="Team or person responsible")
    aws_ssm_slug: str | None = Field(
        None, description="AWS Systems Manager parameter path prefix"
    )


class NamespaceCreate(NamespaceBase):
    """Schema for creating a new namespace."""

    pass


class NamespaceUpdate(BaseModel):
    """Schema for updating an existing namespace (all fields optional)."""

    namespace_id: int | None = Field(None, description="Unique namespace identifier")
    name: str | None = Field(
        None, min_length=1, max_length=255, description="Namespace name"
    )
    slug: str | None = Field(
        None, min_length=1, max_length=255, description="URL-friendly slug"
    )
    icon_class: str | None = Field(None, description="CSS icon class")
    maintained_by: str | None = Field(None, description="Team or person responsible")
    aws_ssm_slug: str | None = Field(
        None, description="AWS Systems Manager parameter path"
    )


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
