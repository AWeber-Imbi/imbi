"""Tests for blueprint-attribute resolution."""

import unittest

from imbi_common import models

from imbi_api import blueprint_attributes


def _blueprint(
    name: str,
    properties: dict,
    *,
    kind: str = 'node',
    project_type: list[str] | None = None,
    environment: list[str] | None = None,
) -> models.Blueprint:
    bp_filter = None
    if project_type is not None or environment is not None:
        bp_filter = models.BlueprintFilter(
            project_type=project_type or [],
            environment=environment or [],
        )
    return models.Blueprint(
        name=name,
        slug=name,
        kind=kind,  # type: ignore[arg-type]
        type=None if kind == 'relationship' else 'Project',
        filter=bp_filter,
        json_schema=models.Schema.model_validate(
            {'type': 'object', 'properties': properties}
        ),
    )


class ResolveTestCase(unittest.TestCase):
    """Tests for ``blueprint_attributes.resolve``."""

    def test_type_scoping_includes_matching_and_unfiltered(self) -> None:
        common = _blueprint(
            'common',
            {'programming_language': {'type': 'string', 'enum': ['Python']}},
        )
        apis = _blueprint(
            'apis',
            {'framework': {'type': 'string', 'enum': ['FastAPI']}},
            project_type=['apis'],
        )
        consumers = _blueprint(
            'consumers',
            {'queue': {'type': 'string'}},
            project_type=['consumers'],
        )

        result = blueprint_attributes.resolve(
            [common, apis, consumers], 'apis'
        )

        self.assertEqual(set(result), {'programming_language', 'framework'})
        self.assertEqual(result['framework'].enum, ['FastAPI'])
        self.assertEqual(result['framework'].type, 'string')

    def test_union_when_type_slug_is_none(self) -> None:
        apis = _blueprint(
            'apis', {'framework': {'type': 'string'}}, project_type=['apis']
        )
        consumers = _blueprint(
            'consumers',
            {'queue': {'type': 'string'}},
            project_type=['consumers'],
        )

        result = blueprint_attributes.resolve([apis, consumers], None)

        self.assertEqual(set(result), {'framework', 'queue'})

    def test_later_blueprint_overrides_same_field(self) -> None:
        first = _blueprint('first', {'framework': {'type': 'string'}})
        second = _blueprint(
            'second',
            {'framework': {'type': 'string', 'enum': ['FastAPI', 'Tornado']}},
        )

        # ``resolve`` expects ascending priority order; the later entry wins.
        result = blueprint_attributes.resolve([first, second], 'apis')

        self.assertEqual(result['framework'].enum, ['FastAPI', 'Tornado'])

    def test_relationship_blueprints_are_ignored(self) -> None:
        rel = models.Blueprint.model_construct(
            name='edge',
            slug='edge',
            kind='relationship',
            type=None,
            filter=None,
            json_schema=models.Schema.model_validate(
                {'type': 'object', 'properties': {'role': {'type': 'string'}}}
            ),
        )

        result = blueprint_attributes.resolve([rel], None)

        self.assertEqual(result, {})

    def test_environment_filter_does_not_exclude(self) -> None:
        env_scoped = _blueprint(
            'env',
            {'deployed_version': {'type': 'string'}},
            project_type=['apis'],
            environment=['production'],
        )

        result = blueprint_attributes.resolve([env_scoped], 'apis')

        self.assertIn('deployed_version', result)
