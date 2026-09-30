"""Tests for the scenario runner and the HTTP client."""

import json
import typing
import unittest

import httpx

from scripts.replay import client, models, scenarios, templates


class FakeApi:
    """A small in-memory API with one collection of tags."""

    def __init__(self) -> None:
        self.tags: dict[str, dict[str, str]] = {}
        self.requests: list[tuple[str, str]] = []
        self.searches = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if request.method == 'POST' and path == '/api/tags/':
            data = json.loads(request.content)
            if data['slug'] in self.tags:
                return httpx.Response(409, json={'detail': 'exists'})
            tag = {'id': f'id-{len(self.tags)}', 'slug': data['slug']}
            self.tags[data['slug']] = tag
            return httpx.Response(201, json=tag)
        if path.startswith('/api/tags/'):
            slug = path.rsplit('/', 1)[-1]
            if slug not in self.tags:
                return httpx.Response(404, json={'detail': 'not found'})
            if request.method == 'DELETE':
                del self.tags[slug]
                return httpx.Response(204)
            return httpx.Response(200, json=self.tags[slug])
        if path == '/api/search':
            self.searches += 1
            hits = [{'id': 'x'}] if self.searches >= 3 else []
            return httpx.Response(200, json=hits)
        if path == '/api/text':
            return httpx.Response(
                200, text='hello', headers={'content-type': 'text/plain'}
            )
        if path == '/api/binary':
            return httpx.Response(
                200, content=b'\x00\x01', headers={'content-type': 'image/png'}
            )
        return httpx.Response(404)


def runner(
    api: FakeApi, moves: list[models.Move] | None = None
) -> scenarios.Runner:
    fake_client = client.Client(
        'http://api', 'token', transport=httpx.MockTransport(api)
    )
    clock = iter(float(value) for value in range(1000))
    return scenarios.Runner(
        client=fake_client,
        routes=templates.RouteTable(
            ('GET /api/tags/{slug}', 'POST /api/tags/')
        ),
        variables={'run': 'r1'},
        moves=moves or [],
        sleep=lambda _seconds: None,
        clock=lambda: next(clock),
    )


def scenario_file(*steps: typing.Any) -> models.ScenarioFile:
    return models.ScenarioFile.model_validate(
        {
            'domain': 'tags',
            'owner': 'J',
            'scenario': [{'name': 'life', 'step': list(steps)}],
        }
    )


class RunnerTestCase(unittest.TestCase):
    def test_lifecycle_with_saved_variable(self) -> None:
        api = FakeApi()
        files = [
            scenario_file(
                {
                    'method': 'POST',
                    'path': '/api/tags/',
                    'body': {'slug': 'tag-{run}'},
                    'expect': 201,
                    'save': {'tag_id': '/id', 'tag_slug': '/slug'},
                },
                {
                    'method': 'GET',
                    'path': '/api/tags/{tag_slug}',
                    'expect': 200,
                },
                {
                    'method': 'POST',
                    'path': '/api/tags/',
                    'body': {'slug': '{tag_slug}'},
                    'expect': 409,
                },
                {
                    'method': 'DELETE',
                    'path': '/api/tags/{tag_slug}',
                    'expect': 204,
                },
            )
        ]
        exchanges, outcomes = runner(api).run(files)
        self.assertEqual(
            [item.status for item in exchanges], [201, 200, 409, 204]
        )
        self.assertEqual(outcomes[0].failures, [])
        self.assertEqual(exchanges[1].path, '/api/tags/tag-r1')
        self.assertEqual(exchanges[1].route, 'GET /api/tags/{slug}')
        self.assertTrue(
            exchanges[0].key.startswith('scenario:tags/life#00 POST')
        )
        self.assertEqual(exchanges[0].request_body, {'slug': 'tag-r1'})

    def test_failure_skips_until_always(self) -> None:
        api = FakeApi()
        files = [
            scenario_file(
                {'method': 'GET', 'path': '/api/tags/none', 'expect': 200},
                {'method': 'GET', 'path': '/api/tags/none'},
                {'method': 'GET', 'path': '/api/tags/none', 'always': True},
            )
        ]
        exchanges, outcomes = runner(api).run(files)
        self.assertEqual([item.status for item in exchanges], [404, 0, 404])
        self.assertEqual(len(outcomes[0].failures), 1)
        self.assertEqual(len(api.requests), 2)

    def test_missing_variable(self) -> None:
        exchanges, outcomes = runner(FakeApi()).run(
            [scenario_file({'method': 'GET', 'path': '/api/tags/{nothing}'})]
        )
        self.assertEqual(exchanges[0].status, 0)
        self.assertIn('nothing', outcomes[0].failures[0])

    def test_save_of_a_missing_value_fails(self) -> None:
        api = FakeApi()
        api.tags['a'] = {'slug': 'a'}
        _, outcomes = runner(api).run(
            [
                scenario_file(
                    {
                        'method': 'GET',
                        'path': '/api/tags/a',
                        'save': {'x': '/id'},
                    }
                )
            ]
        )
        self.assertIn('/id', outcomes[0].failures[0])

    def test_wait_for(self) -> None:
        api = FakeApi()
        step = {
            'method': 'GET',
            'path': '/api/search',
            'wait_for': {'pointer': '/0/id', 'equals': 'x', 'timeout': 10},
        }
        exchanges, outcomes = runner(api).run([scenario_file(step)])
        self.assertEqual(api.searches, 3)
        self.assertEqual(exchanges[0].body, [{'id': 'x'}])
        self.assertEqual(outcomes[0].failures, [])

    def test_wait_for_timeout(self) -> None:
        api = FakeApi()
        step = {
            'method': 'GET',
            'path': '/api/search',
            'wait_for': {'pointer': '/0/id', 'not_equals': 'x', 'timeout': 1},
        }
        api.searches = 2
        _, outcomes = runner(api).run([scenario_file(step)])
        self.assertIn('wait_for', outcomes[0].failures[0])

    def test_moves_apply_to_the_request_path(self) -> None:
        api = FakeApi()
        moves = [models.Move(old='/api/old', new='/api/tags', owner='J')]
        exchanges, _ = runner(api, moves).run(
            [scenario_file({'method': 'GET', 'path': '/api/old/x'})]
        )
        self.assertEqual(api.requests, [('GET', '/api/tags/x')])
        self.assertEqual(exchanges[0].path, '/api/tags/x')


class SubstituteTestCase(unittest.TestCase):
    def test_nested(self) -> None:
        value = scenarios.substitute(
            {'a': ['{x}-1', 2, None], '{x}': True}, {'x': 'v'}
        )
        self.assertEqual(value, {'a': ['v-1', 2, None], 'v': True})

    def test_select(self) -> None:
        body = {'a': [{'b': 1}]}
        self.assertEqual(scenarios.select(body, '/a/0/b'), 1)
        self.assertIs(
            scenarios.select(body, '/a/1/b'), scenarios.pointer.MISSING
        )
        self.assertIs(
            scenarios.select(body, '/a/x'), scenarios.pointer.MISSING
        )
        self.assertIs(scenarios.select(1, '/a'), scenarios.pointer.MISSING)


class ClientTestCase(unittest.TestCase):
    def test_bodies_and_repeat(self) -> None:
        api = FakeApi()
        api.tags['a'] = {'slug': 'a'}
        fake = client.Client(
            'http://api', 'token', transport=httpx.MockTransport(api)
        )
        text = client.capture(
            fake,
            key='k',
            kind='get',
            route='r',
            method='GET',
            path='/api/text',
        )
        self.assertEqual(text.body, {'$text': 'hello'})
        binary = client.capture(
            fake,
            key='k',
            kind='get',
            route='r',
            method='GET',
            path='/api/binary',
        )
        self.assertEqual(binary.body['$length'], 2)
        repeated = client.capture(
            fake,
            key='k',
            kind='get',
            route='r',
            method='GET',
            path='/api/search',
            repeat=3,
        )
        self.assertEqual(len(repeated.elapsed_ms), 3)
        self.assertEqual(repeated.unstable, ['/0'])

    def test_transport_error(self) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('refused', request=request)

        fake = client.Client(
            'http://api', 't', transport=httpx.MockTransport(fail)
        )
        result = fake.send('GET', '/x')
        self.assertEqual(result.status, 0)
        self.assertIn('refused', result.error or '')
