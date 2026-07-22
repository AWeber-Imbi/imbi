from imbi_slackbot import identity, settings, system_prompt
from tests import helpers


class SystemPromptTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        system_prompt._prompt_template = None

    def tearDown(self) -> None:
        settings._slackbot_settings = None
        system_prompt._prompt_template = None
        super().tearDown()

    def test_with_tools(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada Lovelace')
        prompt = system_prompt.build_system_prompt(user, ['list', 'get'])
        self.assertIn('Ada Lovelace', prompt)
        self.assertIn('ada@example.com', prompt)
        self.assertIn('list, get', prompt)
        self.assertNotIn('[Admin]', prompt)

    def test_without_tools(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada')
        prompt = system_prompt.build_system_prompt(user, [])
        self.assertIn('NO tools', prompt)

    def test_admin_flag(self) -> None:
        user = identity.ImbiUser('a@example.com', 'A', is_admin=True)
        prompt = system_prompt.build_system_prompt(user, ['list'])
        self.assertIn('[Admin]', prompt)

    def test_env_override(self) -> None:
        with self.override_environment(
            IMBI_SLACKBOT_SYSTEM_PROMPT='Custom for {display_name}',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada')
            prompt = system_prompt.build_system_prompt(user, ['list'])
        self.assertEqual('Custom for Ada', prompt)

    def test_override_with_stray_braces_falls_back(self) -> None:
        # An operator override containing unescaped braces must not break
        # prompt construction; it falls back to the raw template.
        with self.override_environment(
            IMBI_SLACKBOT_SYSTEM_PROMPT='Example JSON: {"k": "v"}',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada')
            prompt = system_prompt.build_system_prompt(user, ['list'])
        self.assertEqual('Example JSON: {"k": "v"}', prompt)

    def test_injects_base_url(self) -> None:
        with self.override_environment(
            IMBI_UI_URL='https://imbi.example.com',
            IMBI_SLACKBOT_SYSTEM_PROMPT='{links_section}',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada')
            prompt = system_prompt.build_system_prompt(user, ['list'])
        self.assertIn('https://imbi.example.com', prompt)
