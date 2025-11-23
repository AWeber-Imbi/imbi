"""
Pydantic schemas for operations log endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class OperationsLogCreate(BaseModel):
    """Schema for creating an operations log entry."""

    project_id: int = Field(..., description="Project ID")
    environment: str | None = Field(
        None, description="Environment where change occurred"
    )
    change_type: str = Field(
        ..., min_length=1, description="Type of change (deployment, incident, etc.)"
    )
    description: str = Field(..., min_length=1, description="Description of the change")
    occurred_at: datetime = Field(..., description="When the event occurred")
    completed_at: datetime | None = Field(None, description="When the event completed")
    performed_by: str | None = Field(None, description="Who performed the operation")
    link: str | None = Field(None, description="Link to more info (PR, ticket, etc.)")
    notes: str | None = Field(None, description="Additional notes")
    ticket_slug: str | None = Field(None, description="Ticket/issue reference")
    version: str | None = Field(None, description="Version deployed/changed")


class OperationsLogUpdate(BaseModel):
    """Schema for updating an operations log entry."""

    environment: str | None = None
    change_type: str | None = Field(None, min_length=1)
    description: str | None = Field(None, min_length=1)
    occurred_at: datetime | None = None
    completed_at: datetime | None = None
    performed_by: str | None = None
    link: str | None = None
    notes: str | None = None
    ticket_slug: str | None = None
    version: str | None = None


class OperationsLogResponse(BaseModel):
    """Schema for operations log entry response."""

    id: int
    recorded_at: datetime
    recorded_by: str
    occurred_at: datetime
    completed_at: datetime | None
    performed_by: str | None
    project_id: int
    project_name: str | None = Field(None, description="Project name")
    environment: str | None
    change_type: str
    description: str
    link: str | None
    notes: str | None
    ticket_slug: str | None
    version: str | None
    # User details
    email_address: str | None = Field(
        None, description="Email of person who performed the change"
    )
    display_name: str | None = Field(
        None, description="Display name of person who performed the change"
    )

    model_config = {"from_attributes": True}


class OperationsLogListResponse(BaseModel):
    """Schema for operations log list response."""

    entries: list[OperationsLogResponse]
    total: int = Field(..., description="Total number of entries matching filter")
    limit: int
