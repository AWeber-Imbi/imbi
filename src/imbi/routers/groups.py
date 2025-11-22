"""
Group API endpoints.

Groups organize users and define permissions.
"""
import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AdminUser
from imbi.models import Group, GroupMember
from imbi.schemas.group import (
    GroupCreate,
    GroupMemberAdd,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdate,
)

router = APIRouter(tags=["groups"])


@router.get(
    "/groups",
    response_model=list[GroupResponse],
    summary="List all groups",
)
async def list_groups() -> list[dict]:
    """
    Retrieve all groups ordered by name.

    Returns:
        List of all groups
    """
    groups = await Group.select().order_by(Group.name)
    return groups


@router.get(
    "/groups/{group_name}",
    response_model=GroupResponse,
    summary="Get a group",
    responses={
        404: {"description": "Group not found"},
    },
)
async def get_group(group_name: str) -> dict:
    """
    Retrieve a single group by name.

    Args:
        group_name: The group name

    Returns:
        Group details

    Raises:
        HTTPException: 404 if group not found
    """
    group = (
        await Group.select()
        .where(Group.name == group_name)
        .first()
    )

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Group '{group_name}' not found",
            },
        )

    return group


@router.post(
    "/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a group",
    responses={
        201: {"description": "Group created successfully"},
        409: {"description": "Group already exists"},
    },
)
async def create_group(
    group: GroupCreate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Create a new group.

    Requires admin permission.

    Args:
        group: Group data
        user: Authenticated admin user

    Returns:
        Created group

    Raises:
        HTTPException: 409 if group with same name already exists
    """
    # Check for existing group with same name
    existing = await Group.select().where(
        Group.name == group.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": f"Group '{group.name}' already exists",
            },
        )

    # Create group
    now = datetime.datetime.utcnow()
    new_group = Group(
        **group.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )

    await new_group.save()

    # Fetch the created group to return
    result = (
        await Group.select()
        .where(Group.name == new_group.name)
        .first()
    )

    return result


@router.patch(
    "/groups/{group_name}",
    response_model=GroupResponse,
    summary="Update a group",
    responses={
        404: {"description": "Group not found"},
        409: {"description": "Group name conflicts with existing"},
    },
)
async def update_group(
    group_name: str,
    updates: GroupUpdate,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Update an existing group.

    Requires admin permission. Only provided fields will be updated.

    Args:
        group_name: The group name to update
        updates: Group fields to update
        user: Authenticated admin user

    Returns:
        Updated group

    Raises:
        HTTPException: 404 if group not found, 409 if name conflicts
    """
    # Find existing group
    group = (
        await Group.select()
        .where(Group.name == group_name)
        .first()
    )

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Group '{group_name}' not found",
            },
        )

    # Check for conflicts if renaming
    update_data = updates.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] != group_name:
        existing = (
            await Group.select()
            .where(Group.name == update_data["name"])
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "https://imbi.example.com/errors/conflict",
                    "title": "Conflict",
                    "status": 409,
                    "detail": f"Group '{update_data['name']}' already exists",
                },
            )

    # Update group
    if update_data:
        update_data["last_modified_at"] = datetime.datetime.utcnow()
        update_data["last_modified_by"] = user.username

        await Group.update(update_data).where(
            Group.name == group_name
        )

        # If name changed, use new name for fetching
        fetch_name = update_data.get("name", group_name)
    else:
        fetch_name = group_name

    # Fetch updated group
    result = (
        await Group.select()
        .where(Group.name == fetch_name)
        .first()
    )

    return result


@router.delete(
    "/groups/{group_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a group",
    responses={
        204: {"description": "Group deleted successfully"},
        404: {"description": "Group not found"},
    },
)
async def delete_group(
    group_name: str,
    user: AdminUser,  # Requires admin permission
) -> Response:
    """
    Delete a group.

    Requires admin permission. Also deletes all group memberships.

    Args:
        group_name: The group name to delete
        user: Authenticated admin user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if group not found
    """
    # Find existing group
    group = (
        await Group.select()
        .where(Group.name == group_name)
        .first()
    )

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Group '{group_name}' not found",
            },
        )

    # Delete group memberships first
    await GroupMember.delete().where(GroupMember.group == group_name)

    # Delete group
    await Group.delete().where(Group.name == group_name)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Group Member Management


@router.get(
    "/groups/{group_name}/members",
    response_model=list[GroupMemberResponse],
    summary="List group members",
    responses={
        404: {"description": "Group not found"},
    },
)
async def list_group_members(group_name: str) -> list[dict]:
    """
    List all members of a group.

    Args:
        group_name: The group name

    Returns:
        List of group members

    Raises:
        HTTPException: 404 if group not found
    """
    # Verify group exists
    group = await Group.select().where(Group.name == group_name).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Group '{group_name}' not found",
            },
        )

    # Get members
    members = (
        await GroupMember.select()
        .where(GroupMember.group == group_name)
        .order_by(GroupMember.username)
    )

    return members


@router.post(
    "/groups/{group_name}/members",
    response_model=GroupMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a group",
    responses={
        201: {"description": "Member added successfully"},
        404: {"description": "Group not found"},
        409: {"description": "Member already in group"},
    },
)
async def add_group_member(
    group_name: str,
    member: GroupMemberAdd,
    user: AdminUser,  # Requires admin permission
) -> dict:
    """
    Add a user to a group.

    Requires admin permission.

    Args:
        group_name: The group name
        member: Username to add
        user: Authenticated admin user

    Returns:
        Created group membership

    Raises:
        HTTPException: 404 if group not found, 409 if already a member
    """
    # Verify group exists
    group = await Group.select().where(Group.name == group_name).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"Group '{group_name}' not found",
            },
        )

    # Check if already a member
    existing = await GroupMember.select().where(
        (GroupMember.username == member.username)
        & (GroupMember.group == group_name)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://imbi.example.com/errors/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": f"User '{member.username}' is already a member of group '{group_name}'",
            },
        )

    # Add member
    new_member = GroupMember(
        username=member.username,
        group=group_name,
        added_by=user.username,
    )
    await new_member.save()

    # Fetch the created membership to return
    result = (
        await GroupMember.select()
        .where(
            (GroupMember.username == member.username)
            & (GroupMember.group == group_name)
        )
        .first()
    )

    return result


@router.delete(
    "/groups/{group_name}/members/{username}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from a group",
    responses={
        204: {"description": "Member removed successfully"},
        404: {"description": "Group or membership not found"},
    },
)
async def remove_group_member(
    group_name: str,
    username: str,
    user: AdminUser,  # Requires admin permission
) -> Response:
    """
    Remove a user from a group.

    Requires admin permission.

    Args:
        group_name: The group name
        username: Username to remove
        user: Authenticated admin user

    Returns:
        204 No Content on success

    Raises:
        HTTPException: 404 if group or membership not found
    """
    # Find existing membership
    membership = await GroupMember.select().where(
        (GroupMember.username == username)
        & (GroupMember.group == group_name)
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://imbi.example.com/errors/not-found",
                "title": "Not Found",
                "status": 404,
                "detail": f"User '{username}' is not a member of group '{group_name}'",
            },
        )

    # Delete membership
    await GroupMember.delete().where(
        (GroupMember.username == username)
        & (GroupMember.group == group_name)
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
