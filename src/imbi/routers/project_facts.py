"""
Project fact API endpoints.

Manages typed key-value metadata for projects.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser, AuthenticatedUser
from imbi.models import FactType, Project, ProjectFact
from imbi.schemas.project_relations import (
    FactTypeCreate,
    FactTypeResponse,
    FactTypeUpdate,
    ProjectFactCreate,
    ProjectFactResponse,
    ProjectFactUpdate,
)

router = APIRouter(tags=["project-facts"])


# Fact Types (admin-managed)


@router.get(
    "/fact-types",
    response_model=list[FactTypeResponse],
    summary="List all fact types",
)
async def list_fact_types() -> list[dict]:
    """List all fact types ordered by weight."""
    fact_types = await FactType.select().order_by(FactType.weight, FactType.name)
    return fact_types


@router.post(
    "/fact-types",
    response_model=FactTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fact type",
)
async def create_fact_type(
    fact_type: FactTypeCreate,
    user: AdminUser,
) -> dict:
    """Create a new fact type (admin only)."""
    # Check for duplicates
    existing = await FactType.select().where(
        FactType.name == fact_type.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Fact type '{fact_type.name}' already exists",
        )

    now = datetime.utcnow()
    new_fact_type = FactType(
        **fact_type.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )
    await new_fact_type.save()

    return await FactType.select().where(
        FactType.id == new_fact_type.id
    ).first()


# Project Facts (per-project)


@router.get(
    "/projects/{project_id}/facts",
    response_model=list[ProjectFactResponse],
    summary="List project facts",
)
async def list_project_facts(project_id: int) -> list[dict]:
    """
    List all facts for a project.

    Args:
        project_id: The project ID

    Returns:
        List of project facts with fact type details
    """
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Get facts
    facts = await ProjectFact.select().where(
        ProjectFact.project_id == project_id
    )

    # Enrich with fact type names
    for fact in facts:
        fact_type = await FactType.select().where(
            FactType.id == fact["fact_type_id"]
        ).first()
        if fact_type:
            fact["fact_type_name"] = fact_type["name"]

    return facts


@router.post(
    "/projects/{project_id}/facts",
    response_model=ProjectFactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a project fact",
)
async def add_project_fact(
    project_id: int,
    fact: ProjectFactCreate,
    user: AuthenticatedUser,
) -> dict:
    """Add a fact to a project."""
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Verify fact type exists
    fact_type = await FactType.select().where(
        FactType.id == fact.fact_type_id
    ).first()
    if not fact_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact type with ID {fact.fact_type_id} not found",
        )

    # Check for existing fact
    existing = await ProjectFact.select().where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact.fact_type_id)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fact with this type already exists for this project",
        )

    # Create fact
    now = datetime.utcnow()
    new_fact = ProjectFact(
        project_id=project_id,
        **fact.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )
    await new_fact.save()

    # Fetch and enrich result
    result = await ProjectFact.select().where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact.fact_type_id)
    ).first()

    result["fact_type_name"] = fact_type["name"]

    return result


@router.patch(
    "/projects/{project_id}/facts/{fact_type_id}",
    response_model=ProjectFactResponse,
    summary="Update a project fact",
)
async def update_project_fact(
    project_id: int,
    fact_type_id: int,
    updates: ProjectFactUpdate,
    user: AuthenticatedUser,
) -> dict:
    """Update a project fact."""
    # Find existing fact
    fact = await ProjectFact.select().where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact_type_id)
    ).first()

    if not fact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project fact not found",
        )

    # Update fact
    update_data = updates.model_dump(exclude_unset=True)
    update_data["last_modified_at"] = datetime.utcnow()
    update_data["last_modified_by"] = user.username

    await ProjectFact.update(update_data).where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact_type_id)
    )

    # Fetch and enrich updated fact
    result = await ProjectFact.select().where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact_type_id)
    ).first()

    fact_type = await FactType.select().where(
        FactType.id == fact_type_id
    ).first()
    if fact_type:
        result["fact_type_name"] = fact_type["name"]

    return result


@router.delete(
    "/projects/{project_id}/facts/{fact_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project fact",
)
async def remove_project_fact(
    project_id: int,
    fact_type_id: int,
    user: AuthenticatedUser,
) -> Response:
    """Remove a fact from a project."""
    # Find existing fact
    fact = await ProjectFact.select().where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact_type_id)
    ).first()

    if not fact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project fact not found",
        )

    # Delete fact
    await ProjectFact.delete().where(
        (ProjectFact.project_id == project_id)
        & (ProjectFact.fact_type_id == fact_type_id)
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
