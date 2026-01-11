import fastapi

from imbi_gateway import app
from tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)
