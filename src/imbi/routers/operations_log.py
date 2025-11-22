"""
Operations log API endpoints.

Tracks deployments, incidents, changes, and other operational events.
"""
import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from imbi.dependencies import AuthenticatedUser
from imbi.models import OperationsLog, Project, User
from imbi.schemas.operations_log import (
    OperationsLogCreate,
    OperationsLogListResponse,
    OperationsLogResponse,
    OperationsLogUpdate,
)

router = APIRouter(tags=["operations-log"])


@router.get(
    "/operations-log",
    response_model=OperationsLogListResponse,
    summary="List operations log entries",
)
async def list_operations_log(
    limit: int = Query(100, ge=1, le=500, description="Number of results"),
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    namespace_id: Optional[int] = Query(None, description="Filter by namespace ID"),
    from_date: Optional[datetime.datetime] = Query(None, alias="from", description="Start date filter"),
    to_date: Optional[datetime.datetime] = Query(None, alias="to", description="End date filter"),
) -> OperationsLogListResponse:
    """
    List operations log entries with filtering.

    Args:
        limit: Number of entries to return
        project_id: Filter by project
        namespace_id: Filter by namespace
        from_date: Start date for filtering
        to_date: End date for filtering

    Returns:
        List of operations log entries with metadata
    """
    # Build query
    query = OperationsLog.select()

    # Apply filters
    filters = []
    if project_id:
        filters.append(OperationsLog.project_id == project_id)
    if from_date:
        filters.append(OperationsLog.occurred_at >= from_date)
    if to_date:
        filters.append(OperationsLog.occurred_at < to_date)

    # TODO: Add namespace_id filter (requires join with projects table)

    if filters:
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f
        query = query.where(combined_filter)

    # Get total count
    count_query = OperationsLog.select(OperationsLog.id)
    if filters:
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f
        count_query = count_query.where(combined_filter)

    total = len(await count_query)

    # Order by occurred_at (newest first), then by ID
    query = query.order_by(OperationsLog.occurred_at, ascending=False).limit(limit)

    entries = await query

    # Enrich with project names and user details
    for entry in entries:
        # Get project name
        if entry["project_id"]:
            project = await Project.select().where(
                Project.id == entry["project_id"]
            ).first()
            if project:
                entry["project_name"] = project["name"]

        # Get user details
        if entry["performed_by"]:
            user = await User.select().where(
                User.username == entry["performed_by"]
            ).first()
            if user:
                entry["email_address"] = user["email_address"]
                entry["display_name"] = user["display_name"]

    return OperationsLogListResponse(
        entries=entries,
        total=total,
        limit=limit,
    )


@router.get(
    "/operations-log/{entry_id}",
    response_model=OperationsLogResponse,
    summary="Get an operations log entry",
)
async def get_operations_log_entry(entry_id: int) -> dict:
    """
    Get a single operations log entry by ID.

    Args:
        entry_id: The entry ID

    Returns:
        Operations log entry with enriched data
    """
    entry = await OperationsLog.select().where(OperationsLog.id == entry_id).first()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operations log entry {entry_id} not found",
        )

    # Enrich with project name
    if entry["project_id"]:
        project = await Project.select().where(
            Project.id == entry["project_id"]
        ).first()
        if project:
            entry["project_name"] = project["name"]

    # Enrich with user details
    if entry["performed_by"]:
        user = await User.select().where(
            User.username == entry["performed_by"]
        ).first()
        if user:
            entry["email_address"] = user["email_address"]
            entry["display_name"] = user["display_name"]

    return entry


@router.post(
    "/operations-log",
    response_model=OperationsLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an operations log entry",
)
async def create_operations_log_entry(
    entry: OperationsLogCreate,
    user: AuthenticatedUser,
) -> dict:
    """
    Create a new operations log entry.

    Requires authentication.

    Args:
        entry: Operations log entry data
        user: Authenticated user

    Returns:
        Created operations log entry
    """
    # Verify project exists
    project = await Project.select().where(Project.id == entry.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {entry.project_id} not found",
        )

    # Create entry
    now = datetime.datetime.utcnow()
    new_entry = OperationsLog(
        **entry.model_dump(),
        recorded_at=now,
        recorded_by=user.username,
    )
    await new_entry.save()

    # Fetch and return
    result = await get_operations_log_entry(new_entry.id)

    return result


@router.patch(
    "/operations-log/{entry_id}",
    response_model=OperationsLogResponse,
    summary="Update an operations log entry",
)
async def update_operations_log_entry(
    entry_id: int,
    updates: OperationsLogUpdate,
    user: AuthenticatedUser,
) -> dict:
    """
    Update an existing operations log entry.

    Requires authentication.

    Args:
        entry_id: The entry ID
        updates: Fields to update
        user: Authenticated user

    Returns:
        Updated operations log entry
    """
    # Find existing entry
    entry = await OperationsLog.select().where(OperationsLog.id == entry_id).first()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operations log entry {entry_id} not found",
        )

    # Update entry
    update_data = updates.model_dump(exclude_unset=True)
    if update_data:
        await OperationsLog.update(update_data).where(OperationsLog.id == entry_id)

    # Fetch and return
    result = await get_operations_log_entry(entry_id)

    return result


@router.delete(
    "/operations-log/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an operations log entry",
)
async def delete_operations_log_entry(
    entry_id: int,
    user: AuthenticatedUser,
) -> Response:
    """
    Delete an operations log entry.

    Requires authentication.

    Args:
        entry_id: The entry ID
        user: Authenticated user

    Returns:
        204 No Content on success
    """
    # Find existing entry
    entry = await OperationsLog.select().where(OperationsLog.id == entry_id).first()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operations log entry {entry_id} not found",
        )

    # Delete entry
    await OperationsLog.delete().where(OperationsLog.id == entry_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
