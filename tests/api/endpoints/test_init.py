import unittest

import fastapi

from imbi import endpoints
from imbi.endpoints import status


class EndpointsModuleTestCase(unittest.TestCase):
    """Test cases for endpoints module."""

    def test_routers_list_exists(self) -> None:
        """Test that routers list is exported."""
        self.assertTrue(hasattr(endpoints, 'routers'))
        self.assertIsInstance(endpoints.routers, list)

    def test_routers_contains_status_router(self) -> None:
        """Test that routers list contains the status router."""
        self.assertIn(status.status_router, endpoints.routers)

    def test_all_routers_are_api_routers(self) -> None:
        """Test that all items in routers list are APIRouter instances."""
        for router in endpoints.routers:
            self.assertIsInstance(router, fastapi.APIRouter)
