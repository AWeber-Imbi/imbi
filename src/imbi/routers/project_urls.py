"""
Project URL API endpoints.

Manages environment-specific URLs for projects.
"""
import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AuthenticatedUser
from imbi.models import Project, ProjectURL
from imbi.schemas.project_relations import (
    ProjectURLCreate,
    ProjectURLResponse,
    ProjectURLUpdate,
)

router = APIRouter(tags=["project-urls"])


@router.get(
    "/projects/{project_id}/urls",
    response_model=list[ProjectURLResponse],
    summary="List project URLs",
)
async def list_project_urls(project_id: int) -> list[dict]:
    """
    List all environment URLs for a project.

    Args:
        project_id: The project ID

    Returns:
        List of project URLs
    """
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Get URLs
    urls = (
        await ProjectURL.select()
        .where(ProjectURL.project_id == project_id)
        .order_by(ProjectURL.environment)
    )

    return urls


@router.post(
    "/projects/{project_id}/urls",
    response_model=ProjectURLResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a project URL",
)
async def add_project_url(
    project_id: int,
    url_data: ProjectURLCreate,
    user: AuthenticatedUser,
) -> dict:
    """Add an environment-specific URL to a project."""
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Check for existing URL for this environment
    existing = await ProjectURL.select().where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == url_data.environment)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"URL for environment '{url_data.environment}' already exists",
        )

    # Create URL
    now = datetime.datetime.utcnow()
    new_url = ProjectURL(
        project_id=project_id,
        **url_data.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )
    await new_url.save()

    # Fetch result
    result = await ProjectURL.select().where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == url_data.environment)
    ).first()

    return result


@router.patch(
    "/projects/{project_id}/urls/{environment}",
    response_model=ProjectURLResponse,
    summary="Update a project URL",
)
async def update_project_url(
    project_id: int,
    environment: str,
    updates: ProjectURLUpdate,
    user: AuthenticatedUser,
) -> dict:
    """Update a project URL for a specific environment."""
    # Find existing URL
    url = await ProjectURL.select().where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == environment)
    ).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"URL for environment '{environment}' not found",
        )

    # Update URL
    await ProjectURL.update({
        ProjectURL.url: updates.url,
        ProjectURL.last_modified_at: datetime.datetime.utcnow(),
        ProjectURL.last_modified_by: user.username,
    }).where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == environment)
    )

    # Fetch updated URL
    result = await ProjectURL.select().where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == environment)
    ).first()

    return result


@router.delete(
    "/projects/{project_id}/urls/{environment}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project URL",
)
async def remove_project_url(
    project_id: int,
    environment: str,
    user: AuthenticatedUser,
) -> Response:
    """Remove a project URL for a specific environment."""
    # Find existing URL
    url = await ProjectURL.select().where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == environment)
    ).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"URL for environment '{environment}' not found",
        )

    # Delete URL
    await ProjectURL.delete().where(
        (ProjectURL.project_id == project_id)
        & (ProjectURL.environment == environment)
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
