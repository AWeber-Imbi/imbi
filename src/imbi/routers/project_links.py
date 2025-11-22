"""
Project link API endpoints.

Manages external links for projects (GitHub repos, documentation, etc.)
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser, AuthenticatedUser
from imbi.models import Project, ProjectLink, ProjectLinkType
from imbi.schemas.project_relations import (
    ProjectLinkCreate,
    ProjectLinkResponse,
    ProjectLinkTypeCreate,
    ProjectLinkTypeResponse,
    ProjectLinkTypeUpdate,
    ProjectLinkUpdate,
)

router = APIRouter(tags=["project-links"])


# Project Link Types (admin-managed)


@router.get(
    "/project-link-types",
    response_model=list[ProjectLinkTypeResponse],
    summary="List all project link types",
)
async def list_project_link_types() -> list[dict]:
    """List all project link types."""
    link_types = await ProjectLinkType.select().order_by(ProjectLinkType.link_type)
    return link_types


@router.post(
    "/project-link-types",
    response_model=ProjectLinkTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project link type",
)
async def create_project_link_type(
    link_type: ProjectLinkTypeCreate,
    user: AdminUser,
) -> dict:
    """Create a new project link type (admin only)."""
    # Check for duplicates
    existing = await ProjectLinkType.select().where(
        ProjectLinkType.link_type == link_type.link_type
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": "Link type with same name already exists",
            },
        )

    now = datetime.utcnow()
    new_link_type = ProjectLinkType(
        **link_type.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )
    await new_link_type.save()

    return await ProjectLinkType.select().where(
        ProjectLinkType.id == new_link_type.id
    ).first()


# Project Links (per-project)


@router.get(
    "/projects/{project_id}/links",
    response_model=list[ProjectLinkResponse],
    summary="List project links",
)
async def list_project_links(project_id: int) -> list[dict]:
    """
    List all links for a project.

    Args:
        project_id: The project ID

    Returns:
        List of project links with link type details
    """
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Project with ID {project_id} not found",
            },
        )

    # Get links
    links = await ProjectLink.select().where(
        ProjectLink.project_id == project_id
    )

    # Enrich with link type details
    for link in links:
        link_type = await ProjectLinkType.select().where(
            ProjectLinkType.id == link["link_type_id"]
        ).first()
        if link_type:
            link["link_type"] = link_type["link_type"]
            link["icon_class"] = link_type["icon_class"]

    return links


@router.post(
    "/projects/{project_id}/links",
    response_model=ProjectLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a project link",
)
async def add_project_link(
    project_id: int,
    link: ProjectLinkCreate,
    user: AuthenticatedUser,
) -> dict:
    """
    Add a link to a project.

    Args:
        project_id: The project ID
        link: Link data
        user: Authenticated user

    Returns:
        Created project link
    """
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Verify link type exists
    link_type = await ProjectLinkType.select().where(
        ProjectLinkType.id == link.link_type_id
    ).first()
    if not link_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Link type with ID {link.link_type_id} not found",
        )

    # Check for existing link with same type
    existing = await ProjectLink.select().where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link.link_type_id)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Link with this type already exists for this project",
        )

    # Create link
    now = datetime.utcnow()
    new_link = ProjectLink(
        project_id=project_id,
        **link.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )
    await new_link.save()

    # Fetch and enrich result
    result = await ProjectLink.select().where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link.link_type_id)
    ).first()

    result["link_type"] = link_type["link_type"]
    result["icon_class"] = link_type["icon_class"]

    return result


@router.patch(
    "/projects/{project_id}/links/{link_type_id}",
    response_model=ProjectLinkResponse,
    summary="Update a project link",
)
async def update_project_link(
    project_id: int,
    link_type_id: int,
    updates: ProjectLinkUpdate,
    user: AuthenticatedUser,
) -> dict:
    """Update a project link."""
    # Find existing link
    link = await ProjectLink.select().where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link_type_id)
    ).first()

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project link not found",
        )

    # Update link
    await ProjectLink.update({
        ProjectLink.url: updates.url,
        ProjectLink.last_modified_at: datetime.utcnow(),
        ProjectLink.last_modified_by: user.username,
    }).where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link_type_id)
    )

    # Fetch and enrich updated link
    result = await ProjectLink.select().where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link_type_id)
    ).first()

    link_type = await ProjectLinkType.select().where(
        ProjectLinkType.id == link_type_id
    ).first()
    if link_type:
        result["link_type"] = link_type["link_type"]
        result["icon_class"] = link_type["icon_class"]

    return result


@router.delete(
    "/projects/{project_id}/links/{link_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project link",
)
async def remove_project_link(
    project_id: int,
    link_type_id: int,
    user: AuthenticatedUser,
) -> Response:
    """Remove a link from a project."""
    # Find existing link
    link = await ProjectLink.select().where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link_type_id)
    ).first()

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project link not found",
        )

    # Delete link
    await ProjectLink.delete().where(
        (ProjectLink.project_id == project_id)
        & (ProjectLink.link_type_id == link_type_id)
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
