import typing
import unittest

from fastapi import testclient

from imbi_api.endpoints import status
from tests import support

_StatusLiteral = typing.Literal['ok', 'initializing', 'error']


class StatusResponseModelTestCase(unittest.TestCase):
    """Test cases for StatusResponse model."""

    def test_status_response_creation(self) -> None:
        """Test creating a StatusResponse model."""
        response = status.StatusResponse(status='ok')
        self.assertEqual(response.service, 'imbi')
        self.assertEqual(response.status, 'ok')
        # Version is no longer exposed on the unauthenticated /status
        # response surface (L6); confirm the model has no such field.
        self.assertFalse(hasattr(response, 'version'))

    def test_status_response_with_different_status(self) -> None:
        """Test StatusResponse with different status values."""
        values: list[_StatusLiteral] = [
            'ok',
            'initializing',
            'error',
        ]
        for status_value in values:
            response = status.StatusResponse(
                status=status_value,
            )
            self.assertEqual(response.status, status_value)


class StatusEndpointTestCase(support.SharedAppTestCase):
    """Test cases for status endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        self.client = testclient.TestClient(self.test_app)

    def test_get_status(self) -> None:
        """Test GET /status endpoint returns ok status."""
        response = self.client.get('/status')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['service'], 'imbi')
        self.assertEqual(data['status'], 'ok')
        # Unauthenticated /status must not expose the build version (L6).
        self.assertNotIn('version', data)

    def test_get_status_response_model(self) -> None:
        """Test GET /status endpoint returns valid StatusResponse."""
        response = self.client.get('/status')
        self.assertEqual(response.status_code, 200)
        # Validate the response against the model
        status_response = status.StatusResponse(**response.json())
        self.assertIsInstance(status_response, status.StatusResponse)
