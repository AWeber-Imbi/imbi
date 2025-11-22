"""
Project note API endpoints.

Manages free-text notes for projects.
"""
import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from imbi.dependencies import AuthenticatedUser
from imbi.models import Project, ProjectNote
from imbi.schemas.project_relations import (
    ProjectNoteCreate,
    ProjectNoteResponse,
    ProjectNoteUpdate,
)

router = APIRouter(tags=["project-notes"])


@router.get(
    "/projects/{project_id}/notes",
    response_model=list[ProjectNoteResponse],
    summary="List project notes",
)
async def list_project_notes(project_id: int) -> list[dict]:
    """
    List all notes for a project.

    Args:
        project_id: The project ID

    Returns:
        List of project notes ordered by creation date
    """
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Get notes
    notes = (
        await ProjectNote.select()
        .where(ProjectNote.project_id == project_id)
        .order_by(ProjectNote.created_at, ascending=False)
    )

    return notes


@router.post(
    "/projects/{project_id}/notes",
    response_model=ProjectNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a project note",
)
async def add_project_note(
    project_id: int,
    note_data: ProjectNoteCreate,
    user: AuthenticatedUser,
) -> dict:
    """Add a note to a project."""
    # Verify project exists
    project = await Project.select().where(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found",
        )

    # Create note
    now = datetime.datetime.utcnow()
    new_note = ProjectNote(
        project_id=project_id,
        **note_data.model_dump(),
        created_at=now,
        created_by=user.username,
        last_modified_at=now,
        last_modified_by=user.username,
    )
    await new_note.save()

    # Fetch result
    result = await ProjectNote.select().where(
        ProjectNote.note_id == new_note.note_id
    ).first()

    return result


@router.patch(
    "/projects/{project_id}/notes/{note_id}",
    response_model=ProjectNoteResponse,
    summary="Update a project note",
)
async def update_project_note(
    project_id: int,
    note_id: int,
    updates: ProjectNoteUpdate,
    user: AuthenticatedUser,
) -> dict:
    """Update a project note."""
    # Find existing note
    note = await ProjectNote.select().where(
        (ProjectNote.note_id == note_id)
        & (ProjectNote.project_id == project_id)
    ).first()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    # Update note
    await ProjectNote.update({
        ProjectNote.note: updates.note,
        ProjectNote.last_modified_at: datetime.datetime.utcnow(),
        ProjectNote.last_modified_by: user.username,
    }).where(
        ProjectNote.note_id == note_id
    )

    # Fetch updated note
    result = await ProjectNote.select().where(
        ProjectNote.note_id == note_id
    ).first()

    return result


@router.delete(
    "/projects/{project_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project note",
)
async def remove_project_note(
    project_id: int,
    note_id: int,
    user: AuthenticatedUser,
) -> Response:
    """Remove a note from a project."""
    # Find existing note
    note = await ProjectNote.select().where(
        (ProjectNote.note_id == note_id)
        & (ProjectNote.project_id == project_id)
    ).first()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    # Delete note
    await ProjectNote.delete().where(
        ProjectNote.note_id == note_id
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
