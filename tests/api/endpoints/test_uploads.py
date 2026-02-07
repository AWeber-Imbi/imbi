"""Tests for upload CRUD endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import models

from imbi_api import app


class UploadEndpointsTestCase(unittest.TestCase):
    """Test cases for upload CRUD endpoints."""

    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            """Return test auth context."""
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_upload = models.Upload(
            id='test-uuid-1234',
            filename='test.png',
            content_type='image/png',
            size=1024,
            s3_key='uploads/test-uuid-1234/test.png',
            has_thumbnail=True,
            thumbnail_s3_key=('uploads/test-uuid-1234/thumbnail.webp'),
            uploaded_by='admin@example.com',
            created_at=datetime.datetime.now(datetime.UTC),
        )

    @mock.patch('imbi_api.endpoints.uploads.storage')
    @mock.patch('imbi_common.neo4j.upsert')
    @mock.patch(
        'imbi_api.endpoints.uploads.thumbnails.can_thumbnail',
        return_value=False,
    )
    @mock.patch(
        'imbi_api.endpoints.uploads.validation.validate_upload',
    )
    def test_create_upload_success(
        self,
        mock_validate,
        mock_can_thumb,
        mock_upsert,
        mock_storage,
    ) -> None:
        """Test successful file upload."""
        mock_upsert.return_value = 'element123'
        mock_storage.upload = mock.AsyncMock()

        response = self.client.post(
            '/uploads/',
            files={
                'file': ('test.txt', b'hello world', 'image/png'),
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['filename'], 'test.txt')
        self.assertEqual(data['content_type'], 'image/png')
        self.assertEqual(data['size'], 11)
        self.assertFalse(data['has_thumbnail'])
        mock_validate.assert_called_once()
        mock_storage.upload.assert_called_once()

    @mock.patch(
        'imbi_api.endpoints.uploads.validation.validate_upload',
    )
    def test_create_upload_validation_error(
        self,
        mock_validate,
    ) -> None:
        """Test upload with invalid file returns 400."""
        from imbi_api.storage import validation

        mock_validate.side_effect = validation.UploadValidationError(
            'bad file'
        )

        response = self.client.post(
            '/uploads/',
            files={
                'file': ('bad.exe', b'data', 'text/plain'),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('bad file', response.json()['detail'])

    @mock.patch('imbi_api.endpoints.uploads.storage')
    @mock.patch('imbi_common.neo4j.upsert')
    @mock.patch(
        'imbi_api.endpoints.uploads.thumbnails.can_thumbnail',
        return_value=True,
    )
    @mock.patch(
        'imbi_api.endpoints.uploads.thumbnails.generate_thumbnail',
        new_callable=mock.AsyncMock,
        return_value=b'thumb-data',
    )
    @mock.patch(
        'imbi_api.endpoints.uploads.validation.validate_upload',
    )
    def test_create_upload_with_thumbnail(
        self,
        mock_validate,
        mock_gen_thumb,
        mock_can_thumb,
        mock_upsert,
        mock_storage,
    ) -> None:
        """Test upload generates thumbnail for images."""
        mock_upsert.return_value = 'element123'
        mock_storage.upload = mock.AsyncMock()

        response = self.client.post(
            '/uploads/',
            files={
                'file': ('photo.jpg', b'image-data', 'image/jpeg'),
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['has_thumbnail'])
        # Two uploads: original + thumbnail
        self.assertEqual(mock_storage.upload.call_count, 2)

    def test_list_uploads_empty(self) -> None:
        """Test listing uploads when none exist."""

        async def empty_generator():
            """Yield nothing."""
            return
            yield

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            return_value=empty_generator(),
        ):
            response = self.client.get('/uploads/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_uploads_with_data(self) -> None:
        """Test listing uploads returns data."""

        async def upload_generator():
            """Yield test upload."""
            yield self.test_upload

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            return_value=upload_generator(),
        ):
            response = self.client.get('/uploads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], 'test-uuid-1234')

    def test_list_uploads_with_filter(self) -> None:
        """Test listing uploads with content_type filter."""

        async def upload_generator():
            """Yield test upload."""
            yield self.test_upload

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            return_value=upload_generator(),
        ) as mock_fetch:
            response = self.client.get(
                '/uploads/?content_type=image/png',
            )

        self.assertEqual(response.status_code, 200)
        call_args = mock_fetch.call_args
        self.assertEqual(
            call_args[0][1]['content_type'],
            'image/png',
        )

    @mock.patch('imbi_api.endpoints.uploads.storage')
    def test_get_upload_serves_content(self, mock_storage) -> None:
        """Test getting upload serves file content."""
        mock_storage.download = mock.AsyncMock(
            return_value=b'file-data',
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=self.test_upload,
        ):
            response = self.client.get('/uploads/test-uuid-1234')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'file-data')
        self.assertEqual(
            response.headers['content-type'],
            'image/png',
        )
        self.assertIn(
            'max-age=3600',
            response.headers['cache-control'],
        )

    @mock.patch('imbi_api.endpoints.uploads.storage')
    def test_get_upload_s3_missing(self, mock_storage) -> None:
        """Test getting upload when S3 object is missing returns 404."""
        from botocore import exceptions as botocore_exceptions

        mock_storage.download = mock.AsyncMock(
            side_effect=botocore_exceptions.ClientError(
                {
                    'Error': {
                        'Code': 'NoSuchKey',
                        'Message': 'Not found',
                    },
                },
                'GetObject',
            ),
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=self.test_upload,
        ):
            response = self.client.get('/uploads/test-uuid-1234')

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'content not found',
            response.json()['detail'],
        )

    def test_get_upload_not_found(self) -> None:
        """Test getting non-existent upload returns 404."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.get('/uploads/nonexistent')

        self.assertEqual(response.status_code, 404)

    def test_get_upload_meta(self) -> None:
        """Test getting upload metadata."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=self.test_upload,
        ):
            response = self.client.get(
                '/uploads/test-uuid-1234/meta',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], 'test-uuid-1234')
        self.assertEqual(data['filename'], 'test.png')
        self.assertTrue(data['has_thumbnail'])

    @mock.patch('imbi_api.endpoints.uploads.storage')
    def test_get_thumbnail_serves_content(self, mock_storage) -> None:
        """Test getting thumbnail serves image content."""
        mock_storage.download = mock.AsyncMock(
            return_value=b'thumb-data',
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=self.test_upload,
        ):
            response = self.client.get(
                '/uploads/test-uuid-1234/thumbnail',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'thumb-data')
        self.assertEqual(
            response.headers['content-type'],
            'image/webp',
        )
        self.assertIn(
            'max-age=3600',
            response.headers['cache-control'],
        )

    @mock.patch('imbi_api.endpoints.uploads.storage')
    def test_get_thumbnail_s3_missing(self, mock_storage) -> None:
        """Test getting thumbnail when S3 object is missing."""
        from botocore import exceptions as botocore_exceptions

        mock_storage.download = mock.AsyncMock(
            side_effect=botocore_exceptions.ClientError(
                {
                    'Error': {
                        'Code': 'NoSuchKey',
                        'Message': 'Not found',
                    },
                },
                'GetObject',
            ),
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=self.test_upload,
        ):
            response = self.client.get(
                '/uploads/test-uuid-1234/thumbnail',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'thumbnail not found',
            response.json()['detail'],
        )

    def test_get_thumbnail_no_thumbnail(self) -> None:
        """Test getting thumbnail when none exists returns 404."""
        upload_no_thumb = models.Upload(
            id='no-thumb',
            filename='doc.pdf',
            content_type='application/pdf',
            size=1024,
            s3_key='uploads/no-thumb/doc.pdf',
            has_thumbnail=False,
            uploaded_by='admin@example.com',
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=upload_no_thumb,
        ):
            response = self.client.get(
                '/uploads/no-thumb/thumbnail',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'no thumbnail',
            response.json()['detail'],
        )

    @mock.patch('imbi_api.endpoints.uploads.storage')
    def test_delete_upload(self, mock_storage) -> None:
        """Test deleting an upload."""
        mock_storage.delete = mock.AsyncMock()

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=self.test_upload,
            ),
            mock.patch(
                'imbi_common.neo4j.delete_node',
                return_value=True,
            ),
        ):
            response = self.client.delete(
                '/uploads/test-uuid-1234',
            )

        self.assertEqual(response.status_code, 204)
        # Should delete original + thumbnail
        self.assertEqual(mock_storage.delete.call_count, 2)

    def test_delete_upload_not_found(self) -> None:
        """Test deleting non-existent upload returns 404."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.delete(
                '/uploads/nonexistent',
            )

        self.assertEqual(response.status_code, 404)

    def test_requires_authentication(self) -> None:
        """Test that upload endpoints reject unauthenticated."""
        from imbi_api.auth import permissions

        self.test_app.dependency_overrides.clear()
        unauth_client = testclient.TestClient(self.test_app)

        response = unauth_client.get('/uploads/')
        self.assertEqual(response.status_code, 401)

        response = unauth_client.post(
            '/uploads/',
            files={'file': ('test.txt', b'data', 'text/plain')},
        )
        self.assertEqual(response.status_code, 401)

        # Restore override
        async def mock_get_current_user():
            """Return test auth context."""
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
