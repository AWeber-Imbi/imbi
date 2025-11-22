"""
Project Type API endpoints.

Project types categorize projects (e.g., HTTP API, Web Application, Library).
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser
from imbi.models import ProjectType
from imbi.schemas.project_type import (
    ProjectTypeCreate,
    ProjectTypeResponse,
    ProjectTypeUpdate,
)

router = APIRouter(tags=["project-types"])


@router.get(
    "/project-types",
    response_model=list[ProjectTypeResponse],
    summary="List all project types",
)
async def list_project_types() -> list[dict]:
    """
    Retrieve all project types ordered by name.

    Returns:
        List of all project types
    """
    project_types = await ProjectType.select().order_by(ProjectType.name)
    return project_types


@router.get(
    "/project-types/{project_type_id}",
    response_model=ProjectTypeResponse,
    summary="Get a project type",
    responses={
        404: {"description": "Project type not found"},
    },
)
async def get_project_type(project_type_id: int) -> dict:
    """
    Retrieve a single project type by ID.

    Args:
        project_type_id: The project type ID

    Returns:
        Project type details

    Raises:
        HTTPException: 404 if project type not found
    """
    project_type = (
        await ProjectType.select()
        .where(ProjectType.id == project_type_id)
        .first()
    )

    if not project_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Project type with ID {project_type_id} not found",
            },
        )

    return project_type


@router.post(
    "/project-types",
    response_model=ProjectTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project type",
    responses={
        201: {"description": "Project type created successfully"},
        409: {"description": "Project type already exists"},
    },
)
async def create_project_type(
    project_type: ProjectTypeCreate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Create a new project type.

    Requires admin permission.

    Args:
        project_type: Project type data
        user: Authenticated admin user

    Returns:
        Created project type

    Raises:
        HTTPException: 409 if project type with same name or slug already exists
    """
    # Check for existing project type with same name or slug
    existing = await ProjectType.select().where(
        (ProjectType.name == project_type.name)
        | (ProjectType.slug == project_type.slug)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": "Project type with same name or slug already exists",
            },
        )

    # Create project type
    now = datetime.utcnow()
    new_project_type = ProjectType(
        **project_type.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )

    await new_project_type.save()

    # Fetch the created project type to return
    result = (
        await ProjectType.select()
        .where(ProjectType.id == new_project_type.id)
        .first()
    )

    return result


@router.patch(
    "/project-types/{project_type_id}",
    response_model=ProjectTypeResponse,
    summary="Update a project type",
    responses={
        404: {"description": "Project type not found"},
        409: {"description": "Project type name or slug conflicts with existing"},
    },
)
async def update_project_type(
    project_type_id: int,
    updates: ProjectTypeUpdate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Update an existing project type.

    Requires admin permission. Only provided fields will be updated.

    Args:
        project_type_id: The project type ID to update
        updates: Project type fields to update
        user: Authenticated admin user

    Returns:
        Updated project type

    Raises:
        HTTPException: 404 if project type not found, 409 if name/slug conflicts
    """
    # Find existing project type
    project_type = (
        await ProjectType.select()
        .where(ProjectType.id == project_type_id)
        .first()
    )

    if not project_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Project type with ID {project_type_id} not found",
            },
        )

    # Check for conflicts with other project types
    update_data = updates.model_dump(exclude_unset=True)
    if "name" in update_data or "slug" in update_data:
        filters = []
        if "name" in update_data:
            filters.append(ProjectType.name == update_data["name"])
        if "slug" in update_data:
            filters.append(ProjectType.slug == update_data["slug"])

        existing = (
            await ProjectType.select()
            .where(
                (filters[0] if len(filters) == 1 else (filters[0] | filters[1]))
                & (ProjectType.id != project_type["id"])
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "https://imbi.example.com/errors/conflict",
                    "title": "Conflict",
                    "status": 409,
                    "detail": "Project type with same name or slug already exists",
                },
            )

    # Update project type
    if update_data:
        update_data["last_modified_at"] = datetime.utcnow()
        update_data["last_modified_by"] = user.username

        await ProjectType.update(update_data).where(
            ProjectType.id == project_type["id"]
        )

    # Fetch updated project type
    result = (
        await ProjectType.select()
        .where(ProjectType.id == project_type["id"])
        .first()
    )

    return result


@router.delete(
    "/project-types/{project_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project type",
    responses={
        204: {"description": "Project type deleted successfully"},
        404: {"description": "Project type not found"},
    },
)
async def delete_project_type(
    project_type_id: int,
    user: AdminUser,  # Requires admin permission
) -> Response:
    """
    Delete a project type.

    Requires admin permission.

    Args:
        project_type_id: The project type ID to delete
        user: Authenticated admin user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if project type not found
    """
    # Find existing project type
    project_type = (
        await ProjectType.select()
        .where(ProjectType.id == project_type_id)
        .first()
    )

    if not project_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Project type with ID {project_type_id} not found",
            },
        )

    # Delete project type
    await ProjectType.delete().where(ProjectType.id == project_type["id"])

    return Response(status_code=status.HTTP_204_NO_CONTENT)
