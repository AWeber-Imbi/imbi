"""Tests for the request plan and the parameter sources."""

import typing
import unittest

from scripts.replay import models, plan, sources


def document() -> dict[str, typing.Any]:
    return {
        'paths': {
            '/api/status': {'get': {}},
            '/api/o/{org_slug}/teams/': {'get': {}, 'post': {}},
            '/api/o/{org_slug}/teams/{slug}': {
                'get': {
                    'parameters': [
                        {'name': 'org_slug', 'in': 'path', 'required': True},
                        {'name': 'slug', 'in': 'path', 'required': True},
                    ]
                }
            },
            '/api/o/{org_slug}/search': {
                'get': {
                    'parameters': [
                        {'name': 'q', 'in': 'query', 'required': True},
                        {'name': 'limit', 'in': 'query'},
                    ]
                }
            },
            '/api/events/{event_id}': {'get': {}},
            '/api/auth/authorize': {'get': {}},
            '/api/things/{id}': {'get': {}},
            '/api/other/{x}': {'get': {}},
            '/api/check/{id}': {'get': {}},
        }
    }


def config() -> models.RoutesConfig:
    return models.RoutesConfig.model_validate(
        {
            'sources': {
                'team': {
                    'rows': [{'slug': 'b'}, {'slug': 'a'}, {'slug': 'a'}]
                },
                'empty': {'rows': []},
            },
            'route': [
                {'path': '/api/o/{org_slug}/teams/{slug}', 'source': 'team'},
                {
                    'path': '/api/o/{org_slug}/search',
                    'query': {'q': 'x-{org_slug}'},
                },
                {'path': '/api/events/{event_id}', 'source': 'empty'},
                {'path': '/api/auth/authorize', 'skip': 'redirect'},
                {
                    'path': '/api/check/{id}',
                    'source': 'empty',
                    'query': {'c': '{committish}'},
                },
                {'path': '/api/gone', 'skip': 'removed'},
                {'path': '/api/stale/{id}', 'source': 'team'},
            ],
        }
    )


def fetch_from(
    routes: models.RoutesConfig,
) -> typing.Callable[[str, int], list[dict[str, str]]]:
    def fetch(name: str, limit: int) -> list[dict[str, str]]:
        rows = routes.sources[name].rows or []
        return [dict(row) for row in rows[:limit]]

    return fetch


class BuildTestCase(unittest.TestCase):
    def setUp(self) -> None:
        routes = config()
        self.plan = plan.build(
            document(), routes, fetch_from(routes), {'org_slug': 'acme'}, 10
        )

    def keys(self) -> list[str]:
        return [request.key for request in self.plan.requests]

    def test_routes_without_parameters(self) -> None:
        self.assertIn('GET /api/status', self.keys())
        self.assertIn('GET /api/o/acme/teams/', self.keys())

    def test_source_rows_in_order_without_duplicates(self) -> None:
        teams = [
            key for key in self.keys() if '/teams/' in key and key[-1] != '/'
        ]
        self.assertEqual(
            teams, ['GET /api/o/acme/teams/b', 'GET /api/o/acme/teams/a']
        )

    def test_query_values_use_variables(self) -> None:
        self.assertIn('GET /api/o/acme/search?q=x-acme', self.keys())

    def test_placeholder_when_the_source_is_empty(self) -> None:
        request = next(
            item
            for item in self.plan.requests
            if item.route.startswith('GET /api/events')
        )
        self.assertEqual(request.path, f'/api/events/{models.PLACEHOLDER}')
        self.assertTrue(request.placeholder)

    def test_placeholder_fills_query_values(self) -> None:
        missing = models.PLACEHOLDER
        self.assertIn(f'GET /api/check/{missing}?c={missing}', self.keys())

    def test_skipped(self) -> None:
        self.assertEqual(
            self.plan.skipped, {'GET /api/auth/authorize': 'redirect'}
        )

    def test_uncovered(self) -> None:
        self.assertEqual(
            sorted(self.plan.uncovered),
            [
                'GET /api/gone',
                'GET /api/other/{x}',
                'GET /api/stale/{id}',
                'GET /api/things/{id}',
            ],
        )

    def test_cap(self) -> None:
        routes = config()
        capped = plan.build(
            document(), routes, fetch_from(routes), {'org_slug': 'acme'}, 1
        )
        teams = [
            item for item in capped.requests if item.route.endswith('{slug}')
        ]
        self.assertEqual(len(teams), 1)

    def test_required_query_without_value(self) -> None:
        routes = models.RoutesConfig()
        built = plan.build(
            document(), routes, fetch_from(routes), {'org_slug': 'a'}, 5
        )
        self.assertIn('q', built.uncovered['GET /api/o/{org_slug}/search'])


class ConfigTestCase(unittest.TestCase):
    def test_unknown_source(self) -> None:
        with self.assertRaises(ValueError):
            models.RoutesConfig.model_validate(
                {'route': [{'path': '/a/{b}', 'source': 'nothing'}]}
            )

    def test_duplicate_route(self) -> None:
        with self.assertRaises(ValueError):
            models.RoutesConfig.model_validate(
                {
                    'route': [
                        {'path': '/a', 'skip': 'x'},
                        {'path': '/a', 'skip': 'y'},
                    ]
                }
            )

    def test_source_needs_one_query(self) -> None:
        with self.assertRaises(ValueError):
            models.Source.model_validate(
                {'cypher': 'MATCH (n) RETURN n', 'rows': []}
            )
        with self.assertRaises(ValueError):
            models.Source.model_validate({'cypher': 'MATCH (n) RETURN n'})

    def test_unknown_key(self) -> None:
        with self.assertRaises(ValueError):
            models.Step.model_validate(
                {'method': 'GET', 'path': '/a', 'expected': 200}
            )


class SubstituteTestCase(unittest.TestCase):
    def test_cypher_quotes(self) -> None:
        query = sources.substitute(
            'MATCH (o {slug: $org_slug}) RETURN o',
            {'org_slug': "a'b"},
            cypher=True,
        )
        self.assertEqual(query, "MATCH (o {slug: 'a\\'b'}) RETURN o")

    def test_sql_quotes(self) -> None:
        query = sources.substitute('WHERE x = $v', {'v': "a'b"}, cypher=False)
        self.assertEqual(query, "WHERE x = 'a''b'")

    def test_unknown_variable(self) -> None:
        with self.assertRaises(KeyError):
            sources.substitute('$nothing', {}, cypher=True)
