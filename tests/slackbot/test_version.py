import imbi_slackbot
from tests import helpers


class VersionTests(helpers.TestCase):
    def test_version_is_str(self) -> None:
        self.assertIsInstance(imbi_slackbot.version, str)

    def test_version_info(self) -> None:
        self.assertIsInstance(imbi_slackbot.version_info, list)
        self.assertTrue(imbi_slackbot.version_info)
