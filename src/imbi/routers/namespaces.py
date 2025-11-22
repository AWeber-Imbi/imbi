"""
Namespace API endpoints.

Namespaces are organizational units for grouping projects.
"""
import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser
from imbi.models import Namespace
from imbi.schemas import NamespaceCreate, NamespaceResponse, NamespaceUpdate

router = APIRouter(tags=["namespaces"])


@router.get(
    "/namespaces",
    response_model=list[NamespaceResponse],
    summary="List all namespaces",
)
async def list_namespaces() -> list[dict]:
    """
    Retrieve all namespaces ordered by name.

    Returns:
        List of all namespaces
    """
    namespaces = await Namespace.select().order_by(Namespace.name)
    return namespaces


@router.get(
    "/namespaces/{namespace_id}",
    response_model=NamespaceResponse,
    summary="Get a namespace",
    responses={
        404: {"description": "Namespace not found"},
    },
)
async def get_namespace(namespace_id: int) -> dict:
    """
    Retrieve a single namespace by ID.

    Args:
        namespace_id: The namespace ID

    Returns:
        Namespace details

    Raises:
        HTTPException: 404 if namespace not found
    """
    namespace = (
        await Namespace.select()
        .where(Namespace.namespace_id == namespace_id)
        .first()
    )

    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Namespace with ID {namespace_id} not found",
            },
        )

    return namespace


@router.post(
    "/namespaces",
    response_model=NamespaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a namespace",
    responses={
        201: {"description": "Namespace created successfully"},
        409: {"description": "Namespace already exists"},
    },
)
async def create_namespace(
    namespace: NamespaceCreate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Create a new namespace.

    Requires admin permission.

    Args:
        namespace: Namespace data
        user: Authenticated admin user

    Returns:
        Created namespace

    Raises:
        HTTPException: 409 if namespace with same ID, name, or slug already exists
    """
    # Check for existing namespace with same namespace_id, name, or slug
    existing = await Namespace.select().where(
        (Namespace.namespace_id == namespace.namespace_id)
        | (Namespace.name == namespace.name)
        | (Namespace.slug == namespace.slug)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": "Namespace with same ID, name, or slug already exists",
            },
        )

    # Create namespace
    now = datetime.datetime.datetime.utcnow()
    new_namespace = Namespace(
        **namespace.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )

    await new_namespace.save()

    # Fetch the created namespace to return
    result = (
        await Namespace.select()
        .where(Namespace.id == new_namespace.id)
        .first()
    )

    return result


@router.patch(
    "/namespaces/{namespace_id}",
    response_model=NamespaceResponse,
    summary="Update a namespace",
    responses={
        404: {"description": "Namespace not found"},
        409: {"description": "Namespace name or slug conflicts with existing"},
    },
)
async def update_namespace(
    namespace_id: int,
    updates: NamespaceUpdate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Update an existing namespace.

    Requires admin permission. Only provided fields will be updated.

    Args:
        namespace_id: The namespace ID to update
        updates: Namespace fields to update
        user: Authenticated admin user

    Returns:
        Updated namespace

    Raises:
        HTTPException: 404 if namespace not found, 409 if name/slug conflicts
    """
    # Find existing namespace
    namespace = (
        await Namespace.select()
        .where(Namespace.namespace_id == namespace_id)
        .first()
    )

    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Namespace with ID {namespace_id} not found",
            },
        )

    # Check for conflicts with other namespaces
    update_data = updates.model_dump(exclude_unset=True)
    if "name" in update_data or "slug" in update_data or "namespace_id" in update_data:
        filters = []
        if "namespace_id" in update_data:
            filters.append(Namespace.namespace_id == update_data["namespace_id"])
        if "name" in update_data:
            filters.append(Namespace.name == update_data["name"])
        if "slug" in update_data:
            filters.append(Namespace.slug == update_data["slug"])

        existing = (
            await Namespace.select()
            .where(
                (filters[0] if len(filters) == 1 else (filters[0] | filters[1] | filters[2] if len(filters) == 3 else filters[0] | filters[1]))
                & (Namespace.id != namespace["id"])
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
                    "detail": "Namespace with same ID, name, or slug already exists",
                },
            )

    # Update namespace
    if update_data:
        update_data["last_modified_at"] = datetime.datetime.datetime.utcnow()
        update_data["last_modified_by"] = user.username

        await Namespace.update(update_data).where(
            Namespace.id == namespace["id"]
        )

    # Fetch updated namespace
    result = (
        await Namespace.select()
        .where(Namespace.id == namespace["id"])
        .first()
    )

    return result


@router.delete(
    "/namespaces/{namespace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a namespace",
    responses={
        204: {"description": "Namespace deleted successfully"},
        404: {"description": "Namespace not found"},
    },
)
async def delete_namespace(
    namespace_id: int,
    user: AdminUser,  # Requires admin permission
) -> Response:
    """
    Delete a namespace.

    Requires admin permission.

    Args:
        namespace_id: The namespace ID to delete
        user: Authenticated admin user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if namespace not found
    """
    # Find existing namespace
    namespace = (
        await Namespace.select()
        .where(Namespace.namespace_id == namespace_id)
        .first()
    )

    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Namespace with ID {namespace_id} not found",
            },
        )

    # Delete namespace
    await Namespace.delete().where(Namespace.id == namespace["id"])

    return Response(status_code=status.HTTP_204_NO_CONTENT)
