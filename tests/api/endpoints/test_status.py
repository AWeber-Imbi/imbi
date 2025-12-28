import unittest

from fastapi import testclient

from imbi import app, version
from imbi.endpoints import status


class StatusResponseModelTestCase(unittest.TestCase):
    """Test cases for StatusResponse model."""

    def test_status_response_creation(self) -> None:
        """Test creating a StatusResponse model."""
        response = status.StatusResponse(status='ok')
        self.assertEqual(response.service, 'imbi')
        self.assertEqual(response.version, version)
        self.assertEqual(response.status, 'ok')

    def test_status_response_with_different_status(self) -> None:
        """Test StatusResponse with different status values."""
        for status_value in ['ok', 'initializing', 'error']:
            response = status.StatusResponse(status=status_value)
            self.assertEqual(response.status, status_value)


class StatusEndpointTestCase(unittest.TestCase):
    """Test cases for status endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        self.client = testclient.TestClient(app.create_app())

    def test_get_status(self) -> None:
        """Test GET /status endpoint returns ok status."""
        response = self.client.get('/status')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['service'], 'imbi')
        self.assertEqual(data['version'], version)
        self.assertEqual(data['status'], 'ok')

    def test_get_status_response_model(self) -> None:
        """Test GET /status endpoint returns valid StatusResponse."""
        response = self.client.get('/status')
        self.assertEqual(response.status_code, 200)
        # Validate the response against the model
        status_response = status.StatusResponse(**response.json())
        self.assertIsInstance(status_response, status.StatusResponse)
