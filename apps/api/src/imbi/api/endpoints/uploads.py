"""Upload CRUD endpoints."""

import datetime
import logging
import typing
import uuid

import fastapi
from botocore import exceptions as botocore_exceptions
from imbi_common import models, neo4j, settings

from imbi_api import storage
from imbi_api.auth import permissions
from imbi_api.storage import thumbnails, validation

LOGGER = logging.getLogger(__name__)

uploads_router = fastapi.APIRouter(
    prefix='/uploads',
    tags=['Uploads'],
)


class UploadResponse(typing.TypedDict):
    """Response body for upload metadata."""

    id: str
    filename: str
    content_type: str
    size: int
    has_thumbnail: bool
    uploaded_by: str
    created_at: str


def _upload_response(upload: models.Upload) -> UploadResponse:
    """Convert an Upload model to a response dict."""
    return UploadResponse(
        id=upload.id,
        filename=upload.filename,
        content_type=upload.content_type,
        size=upload.size,
        has_thumbnail=upload.has_thumbnail,
        uploaded_by=upload.uploaded_by,
        created_at=upload.created_at.isoformat(),
    )


@uploads_router.post('/', status_code=201)
async def create_upload(
    file: fastapi.UploadFile,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('upload:create')),
    ],
) -> UploadResponse:
    """Upload a file.

    Accepts a multipart file upload, validates the content type and
    size, stores the file in S3, generates a thumbnail for raster
    images, and creates an Upload node in Neo4j.

    Returns:
        Upload metadata including the generated ID.

    Raises:
        400: If the file fails validation.
        401: Not authenticated.
        403: Missing ``upload:create`` permission.

    """
    data = await file.read()
    content_type = file.content_type or 'application/octet-stream'
    filename = file.filename or 'unnamed'

    storage_settings = settings.Storage()

    try:
        validation.validate_upload(
            data,
            content_type,
            storage_settings,
        )
    except validation.UploadValidationError as err:
        raise fastapi.HTTPException(
            status_code=400,
            detail=str(err),
        ) from err

    upload_id = str(uuid.uuid4())
    s3_key = f'uploads/{upload_id}/{filename}'

    # Upload original file
    await storage.upload(s3_key, data, content_type)

    # Generate thumbnail if applicable
    has_thumbnail = False
    thumbnail_s3_key: str | None = None
    if thumbnails.can_thumbnail(content_type):
        try:
            thumb_data = await thumbnails.generate_thumbnail(
                data,
                storage_settings,
            )
            thumbnail_s3_key = f'uploads/{upload_id}/thumbnail.webp'
            await storage.upload(
                thumbnail_s3_key,
                thumb_data,
                'image/webp',
            )
            has_thumbnail = True
        except Exception:
            LOGGER.exception(
                'Failed to generate thumbnail for %s',
                upload_id,
            )

    # Create Neo4j node
    upload_model = models.Upload(
        id=upload_id,
        filename=filename,
        content_type=content_type,
        size=len(data),
        s3_key=s3_key,
        has_thumbnail=has_thumbnail,
        thumbnail_s3_key=thumbnail_s3_key,
        uploaded_by=auth.user.email,
        created_at=datetime.datetime.now(datetime.UTC),
    )

    try:
        await neo4j.upsert(upload_model, {'id': upload_id})
    except Exception:
        LOGGER.exception(
            'Failed to save upload metadata for %s, rolling back S3 objects',
            upload_id,
        )
        await storage.delete(s3_key)
        if thumbnail_s3_key:
            await storage.delete(thumbnail_s3_key)
        raise

    LOGGER.info(
        'Upload %s created by %s (%s, %d bytes)',
        upload_id,
        auth.user.email,
        content_type,
        len(data),
    )

    return _upload_response(upload_model)


@uploads_router.get('/')
async def list_uploads(
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('upload:read')),
    ],
    content_type: str | None = None,
    uploaded_by: str | None = None,
) -> list[UploadResponse]:
    """List uploads with optional filters.

    Parameters:
        content_type: Filter by MIME type.
        uploaded_by: Filter by uploader email.

    Returns:
        List of upload metadata records.

    """
    parameters: dict[str, typing.Any] = {}
    if content_type is not None:
        parameters['content_type'] = content_type
    if uploaded_by is not None:
        parameters['uploaded_by'] = uploaded_by

    uploads = []
    async for upload in neo4j.fetch_nodes(
        models.Upload,
        parameters if parameters else None,
        order_by='created_at',
    ):
        uploads.append(_upload_response(upload))
    return uploads


@uploads_router.get('/{upload_id}')
async def get_upload(
    upload_id: str,
) -> fastapi.responses.Response:
    """Serve the uploaded file.

    Pulls the file through from S3 and serves it directly.

    Returns:
        The file content with appropriate content type.

    Raises:
        404: If the upload does not exist.

    """
    upload = await neo4j.fetch_node(
        models.Upload,
        {'id': upload_id},
    )
    if upload is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Upload {upload_id!r} not found',
        )

    try:
        data = await storage.download(upload.s3_key)
    except botocore_exceptions.ClientError as err:
        if err.response.get('Error', {}).get('Code') == 'NoSuchKey':
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Upload {upload_id!r} content not found',
            ) from err
        raise
    return fastapi.responses.Response(
        content=data,
        media_type=upload.content_type,
        headers={'Cache-Control': 'public, max-age=3600'},
    )


@uploads_router.get('/{upload_id}/meta')
async def get_upload_meta(
    upload_id: str,
) -> UploadResponse:
    """Return upload metadata as JSON.

    Raises:
        404: If the upload does not exist.

    """
    upload = await neo4j.fetch_node(
        models.Upload,
        {'id': upload_id},
    )
    if upload is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Upload {upload_id!r} not found',
        )
    return _upload_response(upload)


@uploads_router.get('/{upload_id}/thumbnail')
async def get_upload_thumbnail(
    upload_id: str,
) -> fastapi.responses.Response:
    """Serve the upload thumbnail.

    Pulls the thumbnail through from S3 and serves it directly.

    Returns:
        The thumbnail image as image/webp.

    Raises:
        404: If the upload does not exist or has no thumbnail.

    """
    upload = await neo4j.fetch_node(
        models.Upload,
        {'id': upload_id},
    )
    if upload is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Upload {upload_id!r} not found',
        )
    if not upload.has_thumbnail or not upload.thumbnail_s3_key:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Upload {upload_id!r} has no thumbnail',
        )

    try:
        data = await storage.download(upload.thumbnail_s3_key)
    except botocore_exceptions.ClientError as err:
        if err.response.get('Error', {}).get('Code') == 'NoSuchKey':
            raise fastapi.HTTPException(
                status_code=404,
                detail=(f'Upload {upload_id!r} thumbnail not found'),
            ) from err
        raise
    return fastapi.responses.Response(
        content=data,
        media_type='image/webp',
        headers={'Cache-Control': 'public, max-age=3600'},
    )


@uploads_router.delete('/{upload_id}', status_code=204)
async def delete_upload(
    upload_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('upload:delete')),
    ],
) -> None:
    """Delete an upload and its S3 objects.

    Removes the Neo4j node and deletes the original file and
    thumbnail (if present) from S3.

    Raises:
        404: If the upload does not exist.

    """
    upload = await neo4j.fetch_node(
        models.Upload,
        {'id': upload_id},
    )
    if upload is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Upload {upload_id!r} not found',
        )

    # Delete Neo4j node first to avoid broken metadata on S3 failure
    await neo4j.delete_node(models.Upload, {'id': upload_id})

    # Delete S3 objects (orphans can be cleaned up later if this fails)
    await storage.delete(upload.s3_key)
    if upload.thumbnail_s3_key:
        await storage.delete(upload.thumbnail_s3_key)

    LOGGER.info('Upload %s deleted by %s', upload_id, auth.user.email)
