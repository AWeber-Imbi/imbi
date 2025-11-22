"""
Pydantic schemas for ProjectType endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectTypeBase(BaseModel):
    """Base project type schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Project type name")
    slug: str = Field(..., min_length=1, max_length=255, description="URL-friendly slug")
    plural_name: str = Field(..., min_length=1, max_length=255, description="Plural form of name")
    icon_class: Optional[str] = Field(None, description="CSS icon class (e.g., FontAwesome)")
    environment_urls: bool = Field(default=False, description="Whether this type has environment-specific URLs")
    description: Optional[str] = Field(None, description="Description of this project type")


class ProjectTypeCreate(ProjectTypeBase):
    """Schema for creating a new project type."""
    pass


class ProjectTypeUpdate(BaseModel):
    """Schema for updating an existing project type (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=255)
    plural_name: Optional[str] = Field(None, min_length=1, max_length=255)
    icon_class: Optional[str] = None
    environment_urls: Optional[bool] = None
    description: Optional[str] = None


class ProjectTypeResponse(ProjectTypeBase):
    """Schema for project type responses (includes audit fields)."""

    id: int = Field(..., description="Internal database ID")
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {
        "from_attributes": True,  # Enable ORM mode
    }
