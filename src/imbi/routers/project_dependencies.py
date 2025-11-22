"""
Project dependency API endpoints.

Manages dependencies between projects.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AuthenticatedUser
from imbi.models import Project, ProjectDependency
from imbi.schemas.project_relations import (
    ProjectDependencyCreate,
    ProjectDependencyResponse,
)

router = APIRouter(tags=["project-dependencies"])


@router.get(
    "/projects/{project_id}/dependencies",
    response_model=list[ProjectDependencyResponse],
    summary="List project dependencies",
    responses={
        404: {"description": "Project not found"},
    },
)
async def list_project_dependencies(project_id: int) -> list[dict]:
    """
    List all dependencies for a project.

    Args:
        project_id: The project ID

    Returns:
        List of dependencies with details

    Raises:
        HTTPException: 404 if project not found
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

    # Get dependencies
    dependencies = (
        await ProjectDependency.select()
        .where(ProjectDependency.project_id == project_id)
    )

    # Enrich with dependency project names
    for dep in dependencies:
        dep_project = await Project.select().where(
            Project.id == dep["dependency_id"]
        ).first()
        if dep_project:
            dep["dependency_name"] = dep_project["name"]

    return dependencies


@router.post(
    "/projects/{project_id}/dependencies",
    response_model=ProjectDependencyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a project dependency",
    responses={
        201: {"description": "Dependency added successfully"},
        404: {"description": "Project not found"},
        409: {"description": "Dependency already exists"},
    },
)
async def add_project_dependency(
    project_id: int,
    dependency: ProjectDependencyCreate,
    user: AuthenticatedUser,
) -> dict:
    """
    Add a dependency to a project.

    Requires authentication.

    Args:
        project_id: The project ID
        dependency: Dependency data
        user: Authenticated user

    Returns:
        Created dependency

    Raises:
        HTTPException: 404 if project or dependency not found, 409 if already exists
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

    # Verify dependency project exists
    dep_project = await Project.select().where(
        Project.id == dependency.dependency_id
    ).first()
    if not dep_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Dependency project with ID {dependency.dependency_id} not found",
            },
        )

    # Check if dependency already exists
    existing = await ProjectDependency.select().where(
        (ProjectDependency.project_id == project_id)
        & (ProjectDependency.dependency_id == dependency.dependency_id)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": "Dependency already exists",
            },
        )

    # Create dependency
    new_dependency = ProjectDependency(
        project_id=project_id,
        dependency_id=dependency.dependency_id,
        added_by=user.username,
    )
    await new_dependency.save()

    # Fetch and enrich result
    result = await ProjectDependency.select().where(
        (ProjectDependency.project_id == project_id)
        & (ProjectDependency.dependency_id == dependency.dependency_id)
    ).first()

    result["dependency_name"] = dep_project["name"]

    return result


@router.delete(
    "/projects/{project_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project dependency",
    responses={
        204: {"description": "Dependency removed successfully"},
        404: {"description": "Dependency not found"},
    },
)
async def remove_project_dependency(
    project_id: int,
    dependency_id: int,
    user: AuthenticatedUser,
) -> Response:
    """
    Remove a dependency from a project.

    Requires authentication.

    Args:
        project_id: The project ID
        dependency_id: The dependency project ID
        user: Authenticated user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if dependency not found
    """
    # Find existing dependency
    dependency = await ProjectDependency.select().where(
        (ProjectDependency.project_id == project_id)
        & (ProjectDependency.dependency_id == dependency_id)
    ).first()

    if not dependency:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": "Dependency not found",
            },
        )

    # Delete dependency
    await ProjectDependency.delete().where(
        (ProjectDependency.project_id == project_id)
        & (ProjectDependency.dependency_id == dependency_id)
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
