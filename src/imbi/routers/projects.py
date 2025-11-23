"""
Project API endpoints.

Projects are the central entity in Imbi, representing services, applications,
libraries, and other software components.
"""

import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser, AuthenticatedUser
from imbi.models import Namespace, Project, ProjectType
from imbi.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])


@router.get(
    "/projects",
    response_model=ProjectListResponse,
    summary="List projects",
)
async def list_projects(
    limit: int = Query(10, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    include_archived: bool = Query(False, description="Include archived projects"),
    namespace_id: int | None = Query(None, description="Filter by namespace ID"),
    project_type_id: int | None = Query(None, description="Filter by project type ID"),
    name: str | None = Query(None, description="Search by project name"),
    sort: str = Query(
        "name asc",
        description="Sort field and direction (e.g., 'name asc', 'project_score desc')",
    ),
) -> ProjectListResponse:
    """
    Retrieve projects with filtering, sorting, and pagination.

    Args:
        limit: Number of projects per page (max 100)
        offset: Offset for pagination
        include_archived: Include archived projects
        namespace_id: Filter by namespace
        project_type_id: Filter by project type
        name: Search by name (full-text search)
        sort: Sort field and direction

    Returns:
        Paginated list of projects with total count
    """
    # Build query
    query = Project.select()

    # Apply filters
    filters = []
    if not include_archived:
        filters.append(~Project.archived)
    if namespace_id:
        filters.append(Project.namespace_id == namespace_id)
    if project_type_id:
        filters.append(Project.project_type_id == project_type_id)
    if name:
        # Simple case-insensitive search
        filters.append(Project.name.ilike(f"%{name}%"))

    if filters:
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f
        query = query.where(combined_filter)

    # Get total count
    count_query = Project.select(Project.id)
    if filters:
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f
        count_query = count_query.where(combined_filter)

    total_count = len(await count_query)

    # Apply sorting
    sort_parts = sort.split()
    if len(sort_parts) == 2:
        sort_field, sort_direction = sort_parts
        if sort_field == "name":
            query = query.order_by(Project.name, ascending=(sort_direction == "asc"))
        elif sort_field == "namespace":
            # TODO: Join with namespace table for sorting
            query = query.order_by(
                Project.namespace_id, ascending=(sort_direction == "asc")
            )
        elif sort_field == "project_type":
            # TODO: Join with project_type table for sorting
            query = query.order_by(
                Project.project_type_id, ascending=(sort_direction == "asc")
            )
        else:
            query = query.order_by(Project.name)
    else:
        query = query.order_by(Project.name)

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Execute query
    projects = await query

    # TODO: For each project, fetch namespace and project_type names
    # This is N+1 query issue - need to implement joins in Piccolo
    # For now, return basic data

    return ProjectListResponse(
        projects=projects,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project",
    responses={
        404: {"description": "Project not found"},
    },
)
async def get_project(project_id: int) -> dict:
    """
    Retrieve a single project by ID.

    Args:
        project_id: The project ID

    Returns:
        Project details with namespace and project type information

    Raises:
        HTTPException: 404 if project not found
    """
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

    # Fetch related namespace and project_type
    # TODO: Implement proper joins - for now fetch separately
    namespace = (
        await Namespace.select().where(Namespace.id == project["namespace_id"]).first()
    )

    project_type = (
        await ProjectType.select()
        .where(ProjectType.id == project["project_type_id"])
        .first()
    )

    # Add computed fields
    if namespace:
        project["namespace"] = namespace["name"]
        project["namespace_slug"] = namespace["slug"]
        project["namespace_icon"] = namespace["icon_class"]

    if project_type:
        project["project_type"] = project_type["name"]
        project["project_icon"] = project_type["icon_class"]

    return project


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    responses={
        201: {"description": "Project created successfully"},
        409: {"description": "Project already exists"},
    },
)
async def create_project(
    project: ProjectCreate,
    user: AuthenticatedUser,  # Any authenticated user can create projects
) -> dict:
    """
    Create a new project.

    Requires authentication.

    Args:
        project: Project data
        user: Authenticated user

    Returns:
        Created project

    Raises:
        HTTPException: 409 if project with same namespace+name or namespace+slug exists
    """
    # Check for existing project with same namespace+name or namespace+slug
    existing = (
        await Project.select()
        .where(
            (Project.namespace_id == project.namespace_id)
            & ((Project.name == project.name) | (Project.slug == project.slug))
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
                "detail": "Project with same name or slug already exists in this namespace",
            },
        )

    # Verify namespace and project_type exist
    namespace = (
        await Namespace.select().where(Namespace.id == project.namespace_id).first()
    )
    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://imbi.example.com/errors/bad-request",
                "title": "Bad Request",
                "status": 400,
                "detail": f"Namespace with ID {project.namespace_id} not found",
            },
        )

    project_type = (
        await ProjectType.select()
        .where(ProjectType.id == project.project_type_id)
        .first()
    )
    if not project_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://imbi.example.com/errors/bad-request",
                "title": "Bad Request",
                "status": 400,
                "detail": f"Project type with ID {project.project_type_id} not found",
            },
        )

    # Create project
    now = datetime.datetime.utcnow()
    new_project = Project(
        **project.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )

    await new_project.save()

    # Fetch the created project with related data
    result = await get_project(new_project.id)

    # TODO: Trigger automations if configured

    return result


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
    responses={
        404: {"description": "Project not found"},
        409: {"description": "Project name or slug conflicts with existing"},
    },
)
async def update_project(
    project_id: int,
    updates: ProjectUpdate,
    user: AuthenticatedUser,  # Any authenticated user can update
) -> dict:
    """
    Update an existing project.

    Requires authentication. Only provided fields will be updated.

    Args:
        project_id: The project ID to update
        updates: Project fields to update
        user: Authenticated user

    Returns:
        Updated project

    Raises:
        HTTPException: 404 if project not found, 409 if name/slug conflicts
    """
    # Find existing project
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

    # Check for conflicts
    update_data = updates.model_dump(exclude_unset=True)

    # Validate foreign keys if being updated
    if "namespace_id" in update_data:
        namespace = (
            await Namespace.select()
            .where(Namespace.id == update_data["namespace_id"])
            .first()
        )
        if not namespace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "type": "https://imbi.example.com/errors/bad-request",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": f"Namespace with ID {update_data['namespace_id']} not found",
                },
            )

    if "project_type_id" in update_data:
        project_type = (
            await ProjectType.select()
            .where(ProjectType.id == update_data["project_type_id"])
            .first()
        )
        if not project_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "type": "https://imbi.example.com/errors/bad-request",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": f"Project type with ID {update_data['project_type_id']} not found",
                },
            )

    # Check for name/slug conflicts within namespace
    if "name" in update_data or "slug" in update_data:
        namespace_id = update_data.get("namespace_id", project["namespace_id"])

        filters = [
            Project.namespace_id == namespace_id,
            Project.id != project_id,
        ]

        if "name" in update_data:
            filters.append(Project.name == update_data["name"])
        if "slug" in update_data:
            filters.append(Project.slug == update_data["slug"])

        # Combine filters
        combined = filters[0] & filters[1]
        if "name" in update_data or "slug" in update_data:
            name_or_slug = (
                filters[2] if len(filters) == 3 else (filters[2] | filters[3])
            )
            combined = combined & name_or_slug

        existing = await Project.select().where(combined).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "https://imbi.example.com/errors/conflict",
                    "title": "Conflict",
                    "status": 409,
                    "detail": "Project with same name or slug already exists in this namespace",
                },
            )

    # Update project
    if update_data:
        update_data["last_modified_at"] = datetime.datetime.utcnow()
        update_data["last_modified_by"] = user.username

        await Project.update(update_data).where(Project.id == project_id)

    # Fetch updated project with related data
    result = await get_project(project_id)

    return result


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    responses={
        204: {"description": "Project deleted successfully"},
        404: {"description": "Project not found"},
    },
)
async def delete_project(
    project_id: int,
    user: AdminUser,  # Requires admin permission
) -> Response:
    """
    Delete a project.

    Requires admin permission.

    Args:
        project_id: The project ID to delete
        user: Authenticated admin user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if project not found
    """
    # Find existing project
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

    # TODO: Delete related records (facts, links, dependencies, etc.)

    # Delete project
    await Project.delete().where(Project.id == project_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
