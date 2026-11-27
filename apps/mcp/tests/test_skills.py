import typing
import unittest

import fastmcp
import httpx2
from fastmcp.skills import client as skills_client

from imbi.mcp import skills

type Body = dict[str, typing.Any]


def _prompt(slug: str, labels: dict[str, int], **fields: typing.Any) -> Body:
    return {
        'id': f'id-{slug}',
        'updated_at': '2026-11-27T00:00:00Z',
        'slug': slug,
        'name': slug.title(),
        'description': f'Use {slug}\n  when asked.',
        'kind': 'generative',
        'default_label': 'production',
        'labels': [{'name': n, 'version': v} for n, v in labels.items()],
        **fields,
    }


PROMPTS = [
    _prompt('review', {'stable': 2, 'production': 1}),
    _prompt('deploy', {'production': 3}),
    _prompt('draft', {}),
    _prompt('decide', {'stable': 1}, kind='decision'),
    _prompt('Not_Valid', {'stable': 1}),
    _prompt('blank', {'stable': 1}, description=' \n '),
]


class PromptSkillsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.status = 200
        self.requests: list[httpx2.Request] = []
        client = httpx2.AsyncClient(
            base_url='http://api', transport=httpx2.MockTransport(self._api)
        )
        self.server = fastmcp.FastMCP('test')
        self.server.add_provider(skills.PromptSkills(client, '/api'))

    def _client(self) -> fastmcp.Client[typing.Any]:
        return fastmcp.Client(
            self.server, extensions=[skills_client.SkillsClientExtension()]
        )

    def _api(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == '/api/prompts/':
            assert request.url.params['namespace'] == skills.NAMESPACE
            return httpx2.Response(self.status, json=PROMPTS)
        *_, slug, _versions, n = request.url.path.split('/')
        return httpx2.Response(200, json={'system': f'# {slug} v{n}\n'})

    async def test_promoted_prompts_are_skills(self) -> None:
        async with self._client() as client:
            listed = await client.list_skills()
            skill = await client.read_skill('skill://review/SKILL.md')
            blank = await client.read_skill('skill://blank/SKILL.md')
        self.assertEqual(
            sorted(s.frontmatter.name for s in listed),
            ['blank', 'deploy', 'review'],
        )
        self.assertEqual(skill.description, 'Use review when asked.')
        self.assertEqual(blank.description, 'Blank')
        text = skill.files['SKILL.md'].decode()
        self.assertTrue(text.startswith('---\n'))
        self.assertIn('# review v2', text)
        paths = {r.url.path for r in self.requests}
        self.assertIn('/api/prompts/mcp-skills/deploy/versions/3', paths)

    async def test_a_version_is_fetched_once(self) -> None:
        async with self._client() as client:
            await client.list_skills()
            await client.list_skills()
        fetched = [
            r for r in self.requests if r.url.path.endswith('/versions/2')
        ]
        self.assertEqual(len(fetched), 1)

    async def test_a_caller_without_prompt_read_gets_no_skills(self) -> None:
        self.status = 403
        async with self._client() as client:
            self.assertEqual(await client.list_skills(), [])
