"""
Pydantic schemas for project relations (dependencies, links, URLs, facts, notes).
"""

from datetime import datetime

from pydantic import BaseModel, Field

# Project Dependencies


class ProjectDependencyCreate(BaseModel):
    """Schema for creating a project dependency."""

    dependency_id: int = Field(..., description="ID of the project being depended upon")


class ProjectDependencyResponse(BaseModel):
    """Schema for project dependency response."""

    project_id: int
    dependency_id: int
    dependency_name: str | None = Field(None, description="Name of the dependency")
    created_at: datetime
    added_by: str

    model_config = {"from_attributes": True}


# Project Link Types


class ProjectLinkTypeCreate(BaseModel):
    """Schema for creating a project link type."""

    link_type: str = Field(
        ..., min_length=1, max_length=255, description="Link type name"
    )
    icon_class: str | None = Field(None, description="CSS icon class")


class ProjectLinkTypeUpdate(BaseModel):
    """Schema for updating a project link type."""

    link_type: str | None = Field(None, min_length=1, max_length=255)
    icon_class: str | None = None


class ProjectLinkTypeResponse(BaseModel):
    """Schema for project link type response."""

    id: int
    link_type: str
    icon_class: str | None
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {"from_attributes": True}


# Project Links


class ProjectLinkCreate(BaseModel):
    """Schema for creating a project link."""

    link_type_id: int = Field(..., description="Link type ID")
    url: str = Field(..., description="URL for the link")


class ProjectLinkUpdate(BaseModel):
    """Schema for updating a project link."""

    url: str = Field(..., description="Updated URL")


class ProjectLinkResponse(BaseModel):
    """Schema for project link response."""

    project_id: int
    link_type_id: int
    link_type: str | None = Field(None, description="Link type name")
    icon_class: str | None = Field(None, description="Icon class for link type")
    url: str
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {"from_attributes": True}


# Project URLs


class ProjectURLCreate(BaseModel):
    """Schema for creating a project URL."""

    environment: str = Field(..., min_length=1, description="Environment name")
    url: str = Field(..., description="Environment-specific URL")


class ProjectURLUpdate(BaseModel):
    """Schema for updating a project URL."""

    url: str = Field(..., description="Updated URL")


class ProjectURLResponse(BaseModel):
    """Schema for project URL response."""

    project_id: int
    environment: str
    url: str
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {"from_attributes": True}


# Project Facts


class FactTypeCreate(BaseModel):
    """Schema for creating a fact type."""

    name: str = Field(..., min_length=1, max_length=255, description="Fact type name")
    fact_type: str = Field(
        ..., description="Data type: string, boolean, integer, decimal, date, timestamp"
    )
    data_type: str | None = Field(None, description="UI data type hint")
    description: str | None = Field(None, description="Description of this fact type")
    ui_options: str | None = Field(None, description="JSON string for UI configuration")
    weight: int = Field(default=0, description="Display order weight")


class FactTypeUpdate(BaseModel):
    """Schema for updating a fact type."""

    name: str | None = Field(None, min_length=1, max_length=255)
    fact_type: str | None = None
    data_type: str | None = None
    description: str | None = None
    ui_options: str | None = None
    weight: int | None = None


class FactTypeResponse(BaseModel):
    """Schema for fact type response."""

    id: int
    name: str
    fact_type: str
    data_type: str | None
    description: str | None
    ui_options: str | None
    weight: int
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {"from_attributes": True}


class ProjectFactCreate(BaseModel):
    """Schema for creating a project fact."""

    fact_type_id: int = Field(..., description="Fact type ID")
    value: str = Field(..., description="Fact value (stored as text)")
    score: float | None = Field(None, description="Optional score for this fact")


class ProjectFactUpdate(BaseModel):
    """Schema for updating a project fact."""

    value: str = Field(..., description="Updated fact value")
    score: float | None = Field(None, description="Updated score")


class ProjectFactResponse(BaseModel):
    """Schema for project fact response."""

    project_id: int
    fact_type_id: int
    fact_type_name: str | None = Field(None, description="Fact type name")
    value: str
    score: float | None
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {"from_attributes": True}


# Project Notes


class ProjectNoteCreate(BaseModel):
    """Schema for creating a project note."""

    note: str = Field(..., min_length=1, description="Note content")


class ProjectNoteUpdate(BaseModel):
    """Schema for updating a project note."""

    note: str = Field(..., min_length=1, description="Updated note content")


class ProjectNoteResponse(BaseModel):
    """Schema for project note response."""

    id: int  # Note ID (Piccolo auto-generated primary key)
    project_id: int
    note: str
    created_at: datetime
    created_by: str
    last_modified_at: datetime
    last_modified_by: str

    model_config = {"from_attributes": True}
