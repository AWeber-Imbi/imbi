"""
Pydantic schemas for operations log endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OperationsLogCreate(BaseModel):
    """Schema for creating an operations log entry."""

    project_id: int = Field(..., description="Project ID")
    environment: Optional[str] = Field(None, description="Environment where change occurred")
    change_type: str = Field(..., min_length=1, description="Type of change (deployment, incident, etc.)")
    description: str = Field(..., min_length=1, description="Description of the change")
    occurred_at: datetime = Field(..., description="When the event occurred")
    completed_at: Optional[datetime] = Field(None, description="When the event completed")
    performed_by: Optional[str] = Field(None, description="Who performed the operation")
    link: Optional[str] = Field(None, description="Link to more info (PR, ticket, etc.)")
    notes: Optional[str] = Field(None, description="Additional notes")
    ticket_slug: Optional[str] = Field(None, description="Ticket/issue reference")
    version: Optional[str] = Field(None, description="Version deployed/changed")


class OperationsLogUpdate(BaseModel):
    """Schema for updating an operations log entry."""

    environment: Optional[str] = None
    change_type: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = Field(None, min_length=1)
    occurred_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    performed_by: Optional[str] = None
    link: Optional[str] = None
    notes: Optional[str] = None
    ticket_slug: Optional[str] = None
    version: Optional[str] = None


class OperationsLogResponse(BaseModel):
    """Schema for operations log entry response."""

    id: int
    recorded_at: datetime
    recorded_by: str
    occurred_at: datetime
    completed_at: Optional[datetime]
    performed_by: Optional[str]
    project_id: int
    project_name: Optional[str] = Field(None, description="Project name")
    environment: Optional[str]
    change_type: str
    description: str
    link: Optional[str]
    notes: Optional[str]
    ticket_slug: Optional[str]
    version: Optional[str]
    # User details
    email_address: Optional[str] = Field(None, description="Email of person who performed the change")
    display_name: Optional[str] = Field(None, description="Display name of person who performed the change")

    model_config = {"from_attributes": True}


class OperationsLogListResponse(BaseModel):
    """Schema for operations log list response."""

    entries: list[OperationsLogResponse]
    total: int = Field(..., description="Total number of entries matching filter")
    limit: int
