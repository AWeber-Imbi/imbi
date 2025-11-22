"""
Pydantic schemas for Environment endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EnvironmentBase(BaseModel):
    """Base environment schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Environment name")
    icon_class: Optional[str] = Field(None, description="CSS icon class (e.g., FontAwesome)")
    description: Optional[str] = Field(None, description="Description of this environment")


class EnvironmentCreate(EnvironmentBase):
    """Schema for creating a new environment."""
    pass


class EnvironmentUpdate(BaseModel):
    """Schema for updating an existing environment (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    icon_class: Optional[str] = None
    description: Optional[str] = None


class EnvironmentResponse(EnvironmentBase):
    """Schema for environment responses (includes audit fields)."""

    id: int = Field(..., description="Internal database ID")
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {
        "from_attributes": True,  # Enable ORM mode
    }
