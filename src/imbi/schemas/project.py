"""
Pydantic schemas for Project endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectBase(BaseModel):
    """Base project schema with common fields."""

    namespace_id: int = Field(..., description="Namespace ID")
    project_type_id: int = Field(..., description="Project type ID")
    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    slug: str = Field(
        ..., min_length=1, max_length=255, description="URL-friendly slug"
    )
    description: str | None = Field(None, description="Project description")
    environments: list[str] | None = Field(None, description="List of environments")
    archived: bool = Field(default=False, description="Whether project is archived")
    configuration_type: str | None = Field(
        None, description="Configuration management type"
    )

    # Integration fields
    sentry_project_slug: str | None = Field(None, description="Sentry project slug")
    sonarqube_project_key: str | None = Field(None, description="SonarQube project key")
    pagerduty_service_id: str | None = Field(None, description="PagerDuty service ID")


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating an existing project (all fields optional)."""

    namespace_id: int | None = None
    project_type_id: int | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    environments: list[str] | None = None
    archived: bool | None = None
    configuration_type: str | None = None
    sentry_project_slug: str | None = None
    sonarqube_project_key: str | None = None
    pagerduty_service_id: str | None = None


class ProjectResponse(ProjectBase):
    """Schema for project responses (includes audit fields and computed fields)."""

    id: int = Field(..., description="Internal database ID")
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    # Computed/joined fields
    namespace: str | None = Field(None, description="Namespace name")
    namespace_slug: str | None = Field(None, description="Namespace slug")
    namespace_icon: str | None = Field(None, description="Namespace icon class")
    project_type: str | None = Field(None, description="Project type name")
    project_icon: str | None = Field(None, description="Project type icon class")
    project_score: float | None = Field(None, description="Computed project score")

    model_config = {
        "from_attributes": True,  # Enable ORM mode
    }


class ProjectListResponse(BaseModel):
    """Schema for project list response with pagination."""

    projects: list[ProjectResponse]
    total: int = Field(..., description="Total number of projects matching filter")
    limit: int = Field(..., description="Number of projects per page")
    offset: int = Field(..., description="Offset for pagination")
