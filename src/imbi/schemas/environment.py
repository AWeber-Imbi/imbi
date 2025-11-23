"""
Pydantic schemas for Environment endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class EnvironmentBase(BaseModel):
    """Base environment schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Environment name")
    icon_class: str | None = Field(
        None, description="CSS icon class (e.g., FontAwesome)"
    )
    description: str | None = Field(None, description="Description of this environment")


class EnvironmentCreate(EnvironmentBase):
    """Schema for creating a new environment."""

    pass


class EnvironmentUpdate(BaseModel):
    """Schema for updating an existing environment (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    icon_class: str | None = None
    description: str | None = None


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
