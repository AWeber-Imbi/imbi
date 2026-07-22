import imbi.slackbot
from tests.slackbot import helpers


class VersionTests(helpers.TestCase):
    def test_version_is_str(self) -> None:
        self.assertIsInstance(imbi.slackbot.version, str)

    def test_version_info(self) -> None:
        self.assertIsInstance(imbi.slackbot.version_info, list)
        self.assertTrue(imbi.slackbot.version_info)
