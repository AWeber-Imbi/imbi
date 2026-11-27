from unittest import mock

from apps.slackbot.tests import helpers
from imbi.common import models
from imbi.common.prompts import resolve
from imbi.slackbot import identity, settings, system_prompt


class SystemPromptTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        # No graph yet: the packaged prompt is used unless overridden.
        graph_patch = mock.patch.object(
            identity, 'get_graph', return_value=None
        )
        graph_patch.start()
        self.addCleanup(graph_patch.stop)

    def tearDown(self) -> None:
        settings._slackbot_settings = None
        super().tearDown()

    async def build(self, user: identity.ImbiUser, tools: list[str]) -> str:
        return (await system_prompt.build_system_prompt(user, tools)).text

    async def test_with_tools(self) -> None:
        user = identity.ImbiUser(
            'ada@example.com', 'Ada Lovelace', 'acme', 'org-1'
        )
        prompt = await self.build(user, ['list', 'get'])
        self.assertIn('Ada Lovelace', prompt)
        self.assertIn('ada@example.com', prompt)
        self.assertIn('list, get', prompt)
        self.assertNotIn('[Admin]', prompt)
        # The tools reach every org of the user; the workspace has one.
        self.assertIn('Work only in the organization `acme`', prompt)

    async def test_without_tools(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada', 'acme', 'org-1')
        prompt = await self.build(user, [])
        self.assertIn('NO tools', prompt)

    async def test_skills_follow_the_prompt(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada', 'acme', 'org-1')
        skill = models.Prompt(
            name='Triage', slug='triage', namespace='imbi-skills'
        )
        result = await system_prompt.build_system_prompt(user, [], [skill])
        self.assertIn('\n\n## Skills', result.text)
        self.assertIn('- **triage**: Triage', result.text)

    async def test_no_skills_still_explains_how_to_create_one(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada', 'acme', 'org-1')
        result = await system_prompt.build_system_prompt(user, [])
        self.assertIn('There are no skills yet.', result.text)
        self.assertIn('`imbi-skills` namespace', result.text)

    async def test_task_link_has_the_org(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada', 'acme', 'org-1')
        prompt = await self.build(user, ['list'])
        self.assertIn('`/tickets/{org_slug}/{short_id}`', prompt)
        self.assertNotIn('/agents/tasks/', prompt)

    async def test_admin_flag(self) -> None:
        user = identity.ImbiUser(
            'a@example.com', 'A', 'acme', 'org-1', is_admin=True
        )
        prompt = await self.build(user, ['list'])
        self.assertIn('[Admin]', prompt)

    async def test_env_override(self) -> None:
        with self.override_environment(
            IMBI_SLACKBOT_SYSTEM_PROMPT='Custom for {{ display_name }}',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada', 'acme', 'org-1')
            prompt = await self.build(user, ['list'])
        self.assertTrue(prompt.startswith('Custom for Ada\n\n## Skills'))

    async def test_literal_braces_in_override_are_kept(self) -> None:
        # Single braces are plain text in Jinja syntax.
        with self.override_environment(
            IMBI_SLACKBOT_SYSTEM_PROMPT='Example JSON: {"k": "v"}',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada', 'acme', 'org-1')
            prompt = await self.build(user, ['list'])
        self.assertTrue(prompt.startswith('Example JSON: {"k": "v"}\n\n'))

    async def test_broken_override_uses_the_packaged_prompt(self) -> None:
        with self.override_environment(
            IMBI_SLACKBOT_SYSTEM_PROMPT='Broken {{ display_name',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada', 'acme', 'org-1')
            prompt = await self.build(user, ['list'])
        self.assertIn('a@example.com', prompt)
        self.assertNotIn('Broken', prompt)

    async def test_injects_base_url(self) -> None:
        with self.override_environment(
            IMBI_UI_URL='https://imbi.example.com',
            IMBI_SLACKBOT_SYSTEM_PROMPT='{{ links_section }}',
        ):
            user = identity.ImbiUser('a@example.com', 'Ada', 'acme', 'org-1')
            prompt = await self.build(user, ['list'])
        self.assertIn('https://imbi.example.com', prompt)

    async def test_reads_the_configured_ref(self) -> None:
        found = mock.AsyncMock(side_effect=resolve.PromptNotFound('x'))
        with (
            mock.patch.object(identity, 'get_graph', return_value=object()),
            mock.patch.object(resolve, 'resolve', found),
        ):
            result = await system_prompt.build_system_prompt(
                identity.ImbiUser('a@example.com', 'Ada', 'acme', 'org-1'), []
            )
        self.assertEqual(result.source, 'fallback')
        self.assertEqual(
            found.await_args.args[1], 'imbi-slackbot/system@stable'
        )

    async def test_passes_the_user_for_a_restricted_model(self) -> None:
        loaded = system_prompt.system.SystemPrompt(text='x', source='cms')
        with mock.patch.object(
            system_prompt.system,
            'load_system_prompt',
            new=mock.AsyncMock(return_value=loaded),
        ) as load:
            await system_prompt.build_system_prompt(
                identity.ImbiUser('a@example.com', 'Ada', 'acme', 'org-1'), []
            )
        self.assertEqual(load.await_args.kwargs['email'], 'a@example.com')
