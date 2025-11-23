"""
Environment API endpoints.

Environments represent deployment targets (production, staging, development, etc.)
"""

import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser
from imbi.models import Environment
from imbi.schemas.environment import (
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
)

router = APIRouter(tags=["environments"])


@router.get(
    "/environments",
    response_model=list[EnvironmentResponse],
    summary="List all environments",
)
async def list_environments() -> list[dict]:
    """
    Retrieve all environments ordered by name.

    Returns:
        List of all environments
    """
    environments = await Environment.select().order_by(Environment.name)
    return environments


@router.get(
    "/environments/{environment_id}",
    response_model=EnvironmentResponse,
    summary="Get an environment",
    responses={
        404: {"description": "Environment not found"},
    },
)
async def get_environment(environment_id: int) -> dict:
    """
    Retrieve a single environment by ID.

    Args:
        environment_id: The environment ID

    Returns:
        Environment details

    Raises:
        HTTPException: 404 if environment not found
    """
    environment = (
        await Environment.select().where(Environment.id == environment_id).first()
    )

    if not environment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Environment with ID {environment_id} not found",
            },
        )

    return environment


@router.post(
    "/environments",
    response_model=EnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an environment",
    responses={
        201: {"description": "Environment created successfully"},
        409: {"description": "Environment already exists"},
    },
)
async def create_environment(
    environment: EnvironmentCreate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Create a new environment.

    Requires admin permission.

    Args:
        environment: Environment data
        user: Authenticated admin user

    Returns:
        Created environment

    Raises:
        HTTPException: 409 if environment with same name already exists
    """
    # Check for existing environment with same name
    existing = (
        await Environment.select().where(Environment.name == environment.name).first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": "Environment with same name already exists",
            },
        )

    # Create environment
    now = datetime.datetime.utcnow()
    new_environment = Environment(
        **environment.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )

    await new_environment.save()

    # Fetch the created environment to return
    result = (
        await Environment.select().where(Environment.id == new_environment.id).first()
    )

    return result


@router.patch(
    "/environments/{environment_id}",
    response_model=EnvironmentResponse,
    summary="Update an environment",
    responses={
        404: {"description": "Environment not found"},
        409: {"description": "Environment name conflicts with existing"},
    },
)
async def update_environment(
    environment_id: int,
    updates: EnvironmentUpdate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Update an existing environment.

    Requires admin permission. Only provided fields will be updated.

    Args:
        environment_id: The environment ID to update
        updates: Environment fields to update
        user: Authenticated admin user

    Returns:
        Updated environment

    Raises:
        HTTPException: 404 if environment not found, 409 if name conflicts
    """
    # Find existing environment
    environment = (
        await Environment.select().where(Environment.id == environment_id).first()
    )

    if not environment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Environment with ID {environment_id} not found",
            },
        )

    # Check for conflicts with other environments
    update_data = updates.model_dump(exclude_unset=True)
    if "name" in update_data:
        existing = (
            await Environment.select()
            .where(
                (Environment.name == update_data["name"])
                & (Environment.id != environment["id"])
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
                    "detail": "Environment with same name already exists",
                },
            )

    # Update environment
    if update_data:
        update_data["last_modified_at"] = datetime.datetime.utcnow()
        update_data["last_modified_by"] = user.username

        await Environment.update(update_data).where(Environment.id == environment["id"])

    # Fetch updated environment
    result = (
        await Environment.select().where(Environment.id == environment["id"]).first()
    )

    return result


@router.delete(
    "/environments/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an environment",
    responses={
        204: {"description": "Environment deleted successfully"},
        404: {"description": "Environment not found"},
    },
)
async def delete_environment(
    environment_id: int,
    user: AdminUser,  # Requires admin permission
) -> Response:
    """
    Delete an environment.

    Requires admin permission.

    Args:
        environment_id: The environment ID to delete
        user: Authenticated admin user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if environment not found
    """
    # Find existing environment
    environment = (
        await Environment.select().where(Environment.id == environment_id).first()
    )

    if not environment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Environment with ID {environment_id} not found",
            },
        )

    # Delete environment
    await Environment.delete().where(Environment.id == environment["id"])

    return Response(status_code=status.HTTP_204_NO_CONTENT)
