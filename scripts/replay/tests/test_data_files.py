"""Check the data files of the tool, so a typing error fails the tests.

These tests read the real files: routes.toml, owners.toml,
path-map.toml, normalize.toml, expected/*.toml, and scenarios/*.toml.
"""

import fnmatch
import pathlib
import re
import typing
import unittest

from scripts.replay import models, scenarios, templates

ROOT = pathlib.Path(__file__).parent.parent
_VARIABLE = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items = typing.cast('dict[object, object]', value)
        return [
            text
            for key, item in items.items()
            for text in _strings(key) + _strings(item)
        ]
    if isinstance(value, list):
        entries = typing.cast('list[object]', value)
        return [text for item in entries for text in _strings(item)]
    return []


class DataFilesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = models.load_toml(
            models.RoutesConfig, ROOT / 'routes.toml'
        )
        self.owners = models.load_toml(
            models.OwnersConfig, ROOT / 'owners.toml'
        )
        self.moves = models.load_toml(
            models.PathMapConfig, ROOT / 'path-map.toml'
        ).move
        self.rules = models.load_toml(
            models.NormalizeConfig, ROOT / 'normalize.toml'
        ).rule
        self.expected = [
            models.load_toml(models.ExpectedConfig, path)
            for path in sorted((ROOT / 'expected').glob('*.toml'))
        ]
        self.scenarios = scenarios.load(ROOT / 'scenarios')

    def test_owner_letters_are_agents(self) -> None:
        agents = set(self.owners.agents)
        self.assertIn(self.owners.default, agents)
        for route, letter in self.owners.routes.items():
            self.assertIn(letter, agents, route)
        for move in self.moves:
            self.assertIn(move.owner, agents, move.old)
        for config in [*self.expected, *self.scenarios]:
            self.assertIn(config.owner, agents, config.domain)

    def test_owner_routes_are_method_and_template(self) -> None:
        for route in self.owners.routes:
            method, _, template = route.partition(' ')
            self.assertIn(method, {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'})
            self.assertTrue(template.startswith('/'), route)

    def test_bound_routes_are_known(self) -> None:
        known = set(self.owners.routes)
        for binding in self.routes.route:
            self.assertTrue(f'GET {binding.path}' in known, binding.path)
            if binding.source is None:
                continue
            source = self.routes.sources[binding.source]
            columns = set(source.columns)
            if source.rows:
                columns = set(source.rows[0])
            if source.rows == []:
                continue
            needed = set(templates.parameters(binding.path)) - {'org_slug'}
            self.assertLessEqual(needed, columns, binding.path)

    def test_every_moved_route_matches_a_route(self) -> None:
        paths = [route.partition(' ')[2] for route in self.owners.routes]
        for move in self.moves:
            prefix = move.old.split('{')[0]
            self.assertTrue(
                any(path.startswith(prefix) for path in paths), move.old
            )

    def test_scenario_variables_have_values(self) -> None:
        globals_ = {'org_slug', 'admin_email', 'run'}
        for scenario_file in self.scenarios:
            for scenario in scenario_file.scenario:
                known = set(globals_)
                for step in scenario.step:
                    texts = _strings(step.path) + _strings(step.query)
                    texts += _strings(step.body)
                    if step.wait_for is not None:
                        texts += _strings(
                            [step.wait_for.equals, step.wait_for.not_equals]
                        )
                    for text in texts:
                        for name in _VARIABLE.findall(text):
                            self.assertIn(
                                name, known, f'{scenario.name}: {step.path}'
                            )
                    known.update(step.save)

    def test_scenario_steps_resolve_to_owned_routes(self) -> None:
        table = templates.RouteTable(tuple(self.owners.routes))
        for scenario_file in self.scenarios:
            for scenario in scenario_file.scenario:
                for step in scenario.step:
                    path = _VARIABLE.sub('x', step.path)
                    self.assertIsNotNone(
                        table.resolve(step.method, path),
                        f'{scenario.name}: {step.method} {step.path}',
                    )

    def test_expected_keys_match_a_scenario_step_or_route(self) -> None:
        keys: list[str] = []
        for scenario_file in self.scenarios:
            for scenario in scenario_file.scenario:
                for index, step in enumerate(scenario.step):
                    keys.append(
                        f'scenario:{scenario_file.domain}/{scenario.name}'
                        f'#{index:02d} {step.method} {step.path}'
                    )
        for config in self.expected:
            for entry in config.difference:
                if entry.key != '*':
                    self.assertTrue(
                        any(
                            fnmatch.fnmatchcase(key, entry.key) for key in keys
                        ),
                        entry.key,
                    )
                if entry.route != '*':
                    self.assertTrue(
                        any(
                            fnmatch.fnmatchcase(route, entry.route)
                            for route in self.owners.routes
                        ),
                        entry.route,
                    )

    def test_normalize_rules_have_valid_pointers(self) -> None:
        for rule in self.rules:
            self.assertTrue(rule.pointer.startswith('/'), rule.pointer)
