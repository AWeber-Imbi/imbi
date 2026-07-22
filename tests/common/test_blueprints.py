import datetime
import typing
import unittest

import pydantic

from imbi.common import blueprints, graph, models

# -- Helpers ---------------------------------------------------------------


def _schema(
    properties: dict[str, typing.Any],
    required: list[str] | None = None,
) -> models.Schema:
    raw: dict[str, typing.Any] = {
        'type': 'object',
        'properties': properties,
    }
    if required:
        raw['required'] = required
    return models.Schema.model_validate(raw)


def _blueprint(
    *,
    properties: dict[str, typing.Any],
    required: list[str] | None = None,
    name: str = 'test',
    bp_type: str = 'Environment',
    priority: int = 0,
    bp_filter: dict[str, typing.Any] | None = None,
) -> models.Blueprint:
    return models.Blueprint(
        name=name,
        type=bp_type,
        priority=priority,
        json_schema=_schema(properties, required),
        filter=bp_filter,
    )


ORG = models.Organization(name='Org', slug='org')


# -- apply_blueprints tests ----------------------------------------------


class ApplyBlueprintsTests(unittest.TestCase):
    def test_no_blueprints_returns_subclass(self) -> None:
        result = blueprints.apply_blueprints(models.Environment, [])
        self.assertTrue(issubclass(result, models.Environment))
        self.assertEqual('Environment', result.__name__)

    def test_string_field(self) -> None:
        bp = _blueprint(
            properties={
                'domain': {
                    'type': 'string',
                    'description': 'Base domain',
                },
            },
            required=['domain'],
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        self.assertIn('domain', result.model_fields)
        instance = result(
            name='Prod',
            slug='prod',
            domain='example.com',
            organization=ORG,
        )
        self.assertEqual('example.com', instance.domain)

    def test_required_field_raises_when_missing(self) -> None:
        bp = _blueprint(
            properties={'domain': {'type': 'string'}},
            required=['domain'],
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        with self.assertRaises(pydantic.ValidationError):
            result(name='T', slug='t', organization=ORG)

    def test_optional_field_defaults_to_none(self) -> None:
        bp = _blueprint(
            properties={'region': {'type': 'string'}},
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(name='T', slug='t', organization=ORG)
        self.assertIsNone(instance.region)

    def test_integer_and_number_fields(self) -> None:
        bp = _blueprint(
            properties={
                'max_instances': {'type': 'integer'},
                'cpu_threshold': {'type': 'number'},
            },
            required=['max_instances'],
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            max_instances=10,
            cpu_threshold=0.75,
            organization=ORG,
        )
        self.assertEqual(10, instance.max_instances)
        self.assertEqual(0.75, instance.cpu_threshold)

    def test_boolean_field(self) -> None:
        bp = _blueprint(
            properties={'is_production': {'type': 'boolean'}},
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            is_production=True,
            organization=ORG,
        )
        self.assertTrue(instance.is_production)

    def test_array_fields(self) -> None:
        bp = _blueprint(
            properties={
                'tags': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'ports': {
                    'type': 'array',
                    'items': {'type': 'integer'},
                },
                'generic_list': {'type': 'array'},
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            tags=['prod', 'web'],
            ports=[80, 443],
            generic_list=[1, 'two', True],
            organization=ORG,
        )
        self.assertEqual(['prod', 'web'], instance.tags)
        self.assertEqual([80, 443], instance.ports)

    def test_object_field(self) -> None:
        bp = _blueprint(
            properties={'metadata': {'type': 'object'}},
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            metadata={'key': 'value'},
            organization=ORG,
        )
        self.assertEqual({'key': 'value'}, instance.metadata)

    def test_email_format(self) -> None:
        bp = _blueprint(
            properties={
                'contact': {'type': 'string', 'format': 'email'},
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            contact='user@example.com',
            organization=ORG,
        )
        self.assertEqual('user@example.com', str(instance.contact))

        with self.assertRaises(pydantic.ValidationError):
            result(
                name='T',
                slug='t',
                contact='bad',
                organization=ORG,
            )

    def test_uri_format(self) -> None:
        bp = _blueprint(
            properties={
                'homepage': {'type': 'string', 'format': 'uri'},
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            homepage='https://example.com',
            organization=ORG,
        )
        self.assertEqual(
            'https://example.com/',
            str(instance.homepage),
        )

    def test_datetime_formats(self) -> None:
        bp = _blueprint(
            properties={
                'ts': {'type': 'string', 'format': 'date-time'},
                'day': {'type': 'string', 'format': 'date'},
                'window': {'type': 'string', 'format': 'time'},
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        now = datetime.datetime.now(datetime.UTC)
        today = now.date()
        t = datetime.time(2, 0, 0)
        instance = result(
            name='T',
            slug='t',
            ts=now,
            day=today,
            window=t,
            organization=ORG,
        )
        self.assertEqual(now, instance.ts)
        self.assertEqual(today, instance.day)
        self.assertEqual(t, instance.window)

    def test_enum_field(self) -> None:
        bp = _blueprint(
            properties={
                'tier': {
                    'type': 'string',
                    'enum': ['dev', 'staging', 'production'],
                },
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='T',
            slug='t',
            tier='production',
            organization=ORG,
        )
        self.assertEqual('production', instance.tier)

        with self.assertRaises(pydantic.ValidationError):
            result(
                name='T',
                slug='t',
                tier='invalid',
                organization=ORG,
            )

    def test_enum_case_coercion(self) -> None:
        bp = _blueprint(
            properties={
                'framework': {
                    'type': 'string',
                    'enum': ['Tornado', 'FastAPI', 'Pylons'],
                },
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        for raw, expected in [
            ('tornado', 'Tornado'),
            ('FASTAPI', 'FastAPI'),
            ('pYlOnS', 'Pylons'),
            ('Tornado', 'Tornado'),
        ]:
            instance = result(
                name='T',
                slug='t',
                framework=raw,
                organization=ORG,
            )
            self.assertEqual(expected, instance.framework)

        with self.assertRaises(pydantic.ValidationError):
            result(
                name='T',
                slug='t',
                framework='django',
                organization=ORG,
            )

    def test_default_values(self) -> None:
        bp = _blueprint(
            properties={
                'region': {
                    'type': 'string',
                    'default': 'us-east-1',
                },
                'replicas': {
                    'type': 'integer',
                    'default': 3,
                },
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(name='T', slug='t', organization=ORG)
        self.assertEqual('us-east-1', instance.region)
        self.assertEqual(3, instance.replicas)

        instance2 = result(
            name='T',
            slug='t',
            region='eu-west-1',
            replicas=5,
            organization=ORG,
        )
        self.assertEqual('eu-west-1', instance2.region)
        self.assertEqual(5, instance2.replicas)

    def test_description_preserved(self) -> None:
        bp = _blueprint(
            properties={
                'domain': {
                    'type': 'string',
                    'description': 'Base domain name',
                },
            },
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        info = result.model_fields['domain']
        self.assertEqual('Base domain name', info.description)

    def test_multiple_blueprints(self) -> None:
        bp1 = _blueprint(
            properties={'field1': {'type': 'string'}},
            name='base',
            priority=0,
        )
        bp2 = _blueprint(
            properties={'field2': {'type': 'integer'}},
            name='extended',
            priority=1,
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp1, bp2],
        )
        self.assertIn('field1', result.model_fields)
        self.assertIn('field2', result.model_fields)

    def test_json_schema_round_trip(self) -> None:
        bp = _blueprint(
            properties={
                'domain': {
                    'type': 'string',
                    'description': 'Base domain name',
                },
                'region': {
                    'type': 'string',
                    'description': 'AWS region',
                },
            },
            required=['domain', 'region'],
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        schema = result.model_json_schema()
        self.assertIn('domain', schema['properties'])
        self.assertIn('region', schema['properties'])
        self.assertIn('domain', schema['required'])
        self.assertIn('region', schema['required'])

    def test_serialization(self) -> None:
        bp = _blueprint(
            properties={
                'domain': {'type': 'string'},
                'max_instances': {'type': 'integer'},
            },
            required=['domain'],
        )
        result = blueprints.apply_blueprints(
            models.Environment,
            [bp],
        )
        instance = result(
            name='Prod',
            slug='prod',
            domain='example.com',
            max_instances=10,
            organization=ORG,
        )
        data = instance.model_dump()
        self.assertEqual('Prod', data['name'])
        self.assertEqual('example.com', data['domain'])

        json_str = instance.model_dump_json()
        self.assertIn('Prod', json_str)
        self.assertIn('example.com', json_str)


# -- _coerce_enum_case tests ----------------------------------------------


class CoerceEnumCaseTests(unittest.TestCase):
    def test_non_string_passthrough(self) -> None:
        coerce = blueprints._coerce_enum_case(['A', 'B'])
        self.assertEqual(42, coerce(42))
        self.assertIsNone(coerce(None))
        self.assertEqual(['a'], coerce(['a']))


# -- _map_array_type tests ------------------------------------------------


class MapArrayTypeTests(unittest.TestCase):
    def _schema(self, **kwargs: typing.Any) -> typing.Any:
        class S:
            pass

        obj = S()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

    def test_number_items(self) -> None:
        items = self._schema(type='number')
        schema = self._schema(items=items)
        self.assertEqual(list[float], blueprints._map_array_type(schema))

    def test_boolean_items(self) -> None:
        items = self._schema(type='boolean')
        schema = self._schema(items=items)
        self.assertEqual(list[bool], blueprints._map_array_type(schema))

    def test_unknown_items_type(self) -> None:
        items = self._schema(type='object')
        schema = self._schema(items=items)
        self.assertEqual(list, blueprints._map_array_type(schema))

    def test_no_items(self) -> None:
        schema = self._schema(items=None)
        self.assertEqual(list, blueprints._map_array_type(schema))


# -- _map_schema_type_to_python tests --------------------------------------


class MapSchemaTypeToPythonTests(unittest.TestCase):
    def test_unknown_type(self) -> None:
        class S:
            type = None

        self.assertEqual(
            (typing.Any, None),
            blueprints._map_schema_type_to_python(S()),
        )


# -- make_response_model tests --------------------------------------------


class MakeResponseModelTests(unittest.TestCase):
    def test_adds_relationships_field(self) -> None:
        class Simple(pydantic.BaseModel):
            name: str

        response_cls = blueprints.make_response_model(Simple)
        self.assertTrue(issubclass(response_cls, Simple))
        self.assertIn('relationships', response_cls.model_fields)

        instance = response_cls(name='test')
        self.assertIsNone(instance.relationships)

        instance2 = response_cls(
            name='test',
            relationships={
                'teams': models.RelationshipLink(
                    href='/teams',
                    count=5,
                ),
            },
        )
        self.assertEqual(5, instance2.relationships['teams'].count)

    def test_keeps_existing_relationships_field(self) -> None:
        """When the base model already declares ``relationships``,
        ``make_response_model`` must not override it — otherwise the
        emitted OpenAPI schema would drift from the runtime shape.
        """

        class Typed(pydantic.BaseModel):
            href: str

        class Base(pydantic.BaseModel):
            name: str
            relationships: Typed | None = None

        response_cls = blueprints.make_response_model(Base)
        field = response_cls.model_fields['relationships']
        # The annotation must still resolve to the base's typed model,
        # not the dict[str, RelationshipLink] default override.
        self.assertEqual(field.annotation, Typed | None)
        # And the override path must not have been taken.
        self.assertNotEqual(
            field.annotation,
            dict[str, models.RelationshipLink] | None,
        )


# -- _matches_filter tests ------------------------------------------------


class MatchesFilterTests(unittest.TestCase):
    def _bp(
        self,
        bp_filter: dict[str, typing.Any] | None = None,
    ) -> models.Blueprint:
        return _blueprint(
            properties={},
            bp_type='Project',
            bp_filter=bp_filter,
        )

    def test_no_filter_matches_everything(self) -> None:
        bp = self._bp()
        self.assertTrue(blueprints._matches_filter(bp, None))
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {'project_type': 'apis'},
            ),
        )

    def test_filter_with_no_context_rejects(self) -> None:
        bp = self._bp({'project_type': ['apis']})
        self.assertFalse(blueprints._matches_filter(bp, None))

    def test_filter_matches_context(self) -> None:
        bp = self._bp({'project_type': ['apis']})
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {'project_type': 'apis'},
            ),
        )
        self.assertFalse(
            blueprints._matches_filter(
                bp,
                {'project_type': 'consumers'},
            ),
        )

    def test_list_filter_matches_any(self) -> None:
        bp = self._bp(
            {'project_type': ['apis', 'consumers', 'daemons']},
        )
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {'project_type': 'apis'},
            ),
        )
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {'project_type': 'daemons'},
            ),
        )
        self.assertFalse(
            blueprints._matches_filter(
                bp,
                {'project_type': 'database'},
            ),
        )

    def test_multiple_filter_fields_and(self) -> None:
        bp = self._bp(
            {
                'project_type': ['apis'],
                'environment': ['production'],
            }
        )
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {
                    'project_type': 'apis',
                    'environment': 'production',
                },
            ),
        )
        self.assertFalse(
            blueprints._matches_filter(
                bp,
                {
                    'project_type': 'apis',
                    'environment': 'staging',
                },
            ),
        )
        self.assertFalse(
            blueprints._matches_filter(
                bp,
                {'project_type': 'apis'},
            ),
        )

    def test_list_context_value_matches(self) -> None:
        bp = self._bp({'project_type': ['apis']})
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {'project_type': ['apis', 'consumers']},
            ),
        )

    def test_list_context_value_no_match(self) -> None:
        bp = self._bp({'project_type': ['apis']})
        self.assertFalse(
            blueprints._matches_filter(
                bp,
                {'project_type': ['consumers', 'daemons']},
            ),
        )

    def test_empty_filter_lists_match_everything(self) -> None:
        bp = self._bp(
            {
                'project_type': [],
                'environment': [],
            }
        )
        self.assertTrue(blueprints._matches_filter(bp, None))
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {'project_type': 'apis'},
            ),
        )


# -- RelationshipEdge unit tests ------------------------------------------


class RelationshipEdgeTests(unittest.TestCase):
    def test_extra_ignored(self) -> None:
        edge = models.RelationshipEdge(unknown='value')
        self.assertFalse(hasattr(edge, 'unknown'))

    def test_empty_model(self) -> None:
        edge = models.RelationshipEdge()
        self.assertEqual({}, edge.model_dump())


# -- Relationship blueprint model validation ------------------------------


class RelationshipBlueprintModelTests(unittest.TestCase):
    def test_relationship_blueprint_creation(self) -> None:
        bp = models.Blueprint(
            name='Deploy Props',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            json_schema=_schema(
                properties={
                    'url': {'type': 'string', 'format': 'uri'},
                },
            ),
        )
        self.assertEqual('relationship', bp.kind)
        self.assertEqual('Project', bp.source)
        self.assertEqual('Environment', bp.target)
        self.assertEqual('DEPLOYED_IN', bp.edge)
        self.assertIsNone(bp.type)

    def test_relationship_blueprint_missing_source(self) -> None:
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint(
                name='Bad',
                kind='relationship',
                target='Environment',
                edge='DEPLOYED_IN',
                json_schema=_schema(properties={}),
            )
        self.assertIn(
            'source required for relationship blueprints',
            str(ctx.exception),
        )

    def test_node_blueprint_missing_type(self) -> None:
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint(
                name='Bad',
                kind='node',
                json_schema=_schema(properties={}),
            )
        self.assertIn(
            'type is required for node blueprints',
            str(ctx.exception),
        )

    def test_node_blueprint_rejects_relationship_fields(self) -> None:
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint(
                name='Bad',
                type='Project',
                source='Project',
                target='Environment',
                edge='DEPLOYED_IN',
                json_schema=_schema(properties={}),
            )
        self.assertIn(
            'source, target, edge must be None for node blueprints',
            str(ctx.exception),
        )

    def test_node_blueprint_defaults_kind(self) -> None:
        bp = models.Blueprint(
            name='Test',
            type='Project',
            json_schema=_schema(properties={}),
        )
        self.assertEqual('node', bp.kind)


# -- apply_blueprints with RelationshipEdge ------------------------------


class ApplyBlueprintsEdgeTests(unittest.TestCase):
    def test_edge_model_with_blueprint(self) -> None:
        bp = models.Blueprint(
            name='deploy-props',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            json_schema=_schema(
                properties={
                    'url': {
                        'type': 'string',
                        'format': 'uri',
                        'description': 'Deployment URL',
                    },
                },
            ),
        )
        result = blueprints.apply_blueprints(
            models.RelationshipEdge,
            [bp],
        )
        self.assertIn('url', result.model_fields)
        instance = result(url='https://example.com')
        self.assertEqual(
            'https://example.com/',
            str(instance.url),
        )

    def test_multiple_edge_blueprints(self) -> None:
        bp1 = models.Blueprint(
            name='deploy-url',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            priority=0,
            json_schema=_schema(
                properties={
                    'url': {'type': 'string', 'format': 'uri'},
                },
            ),
        )
        bp2 = models.Blueprint(
            name='deploy-tag',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            priority=1,
            json_schema=_schema(
                properties={
                    'deploy_tag': {'type': 'string'},
                },
            ),
        )
        result = blueprints.apply_blueprints(
            models.RelationshipEdge,
            [bp1, bp2],
        )
        self.assertIn('url', result.model_fields)
        self.assertIn('deploy_tag', result.model_fields)


# -- get_model integration test -------------------------------------------


class GetModelIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Integration test for get_model with a real graph."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.graph = graph.Graph()
        await self.graph.open()
        await self.graph.execute(
            'MATCH (b:Blueprint {{name: {name}}}) '
            'DETACH DELETE b RETURN 1 AS ok',
            {'name': 'test-rtt'},
        )

    async def asyncTearDown(self) -> None:
        await self.graph.execute(
            'MATCH (n) DETACH DELETE n RETURN count(n) AS deleted',
        )
        await self.graph.close()

    async def test_round_trip(self) -> None:
        bp = models.Blueprint(
            name='test-rtt',
            type='Environment',
            description='Round-trip test blueprint',
            json_schema=_schema(
                properties={
                    'domain': {
                        'title': 'Domain',
                        'type': 'string',
                        'description': 'Base domain for services.',
                    },
                    'region': {
                        'title': 'AWS Region',
                        'type': 'string',
                        'description': 'AWS region for environment.',
                    },
                    'max_instances': {
                        'title': 'Max Instances',
                        'type': 'integer',
                        'default': 10,
                        'description': 'Maximum number of instances.',
                    },
                },
                required=['domain', 'region'],
            ),
        )
        await self.graph.merge(bp, match_on=['name'])

        result = await blueprints.get_model(
            self.graph,
            models.Environment,
        )

        self.assertIn('domain', result.model_fields)
        self.assertIn('region', result.model_fields)
        self.assertIn('max_instances', result.model_fields)

        self.assertEqual(
            'Base domain for services.',
            result.model_fields['domain'].description,
        )

        instance = result(
            name='Production',
            slug='prod',
            domain='example.com',
            region='us-east-1',
            organization=ORG,
        )
        self.assertEqual('example.com', instance.domain)
        self.assertEqual(10, instance.max_instances)


# -- get_edge_model integration test --------------------------------------


class GetEdgeModelIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Integration test for get_edge_model with a real graph."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.graph = graph.Graph()
        await self.graph.open()
        await self.graph.execute(
            'MATCH (b:Blueprint) DETACH DELETE b RETURN count(b) AS deleted',
        )

    async def asyncTearDown(self) -> None:
        await self.graph.execute(
            'MATCH (n) DETACH DELETE n RETURN count(n) AS deleted',
        )
        await self.graph.close()

    async def test_round_trip(self) -> None:
        bp = models.Blueprint(
            name='test-edge-rtt',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            json_schema=_schema(
                properties={
                    'url': {
                        'type': 'string',
                        'format': 'uri',
                        'description': 'Deployment URL',
                    },
                },
            ),
        )
        await self.graph.merge(bp, match_on=['name'])

        result = await blueprints.get_edge_model(
            self.graph,
            'Project',
            'Environment',
            'DEPLOYED_IN',
        )
        self.assertIn('url', result.model_fields)
        self.assertTrue(
            issubclass(result, models.RelationshipEdge),
        )

    async def test_does_not_mix_with_node_blueprints(self) -> None:
        node_bp = models.Blueprint(
            name='test-edge-node',
            type='Project',
            json_schema=_schema(
                properties={
                    'domain': {'type': 'string'},
                },
            ),
        )
        edge_bp = models.Blueprint(
            name='test-edge-rel',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            json_schema=_schema(
                properties={
                    'url': {'type': 'string', 'format': 'uri'},
                },
            ),
        )
        await self.graph.merge(node_bp, match_on=['name'])
        await self.graph.merge(edge_bp, match_on=['name'])

        edge_model = await blueprints.get_edge_model(
            self.graph,
            'Project',
            'Environment',
            'DEPLOYED_IN',
        )
        self.assertIn('url', edge_model.model_fields)
        self.assertNotIn('domain', edge_model.model_fields)

        node_model = await blueprints.get_model(
            self.graph,
            models.Project,
        )
        self.assertIn('domain', node_model.model_fields)
        self.assertNotIn('url', node_model.model_fields)

    async def test_filter_matching(self) -> None:
        bp = models.Blueprint(
            name='test-edge-filtered',
            kind='relationship',
            source='Project',
            target='Environment',
            edge='DEPLOYED_IN',
            filter={'environment': ['production']},
            json_schema=_schema(
                properties={
                    'deploy_tag': {'type': 'string'},
                },
            ),
        )
        await self.graph.merge(bp, match_on=['name'])

        result = await blueprints.get_edge_model(
            self.graph,
            'Project',
            'Environment',
            'DEPLOYED_IN',
            context={'environment': 'production'},
        )
        self.assertIn('deploy_tag', result.model_fields)

        result_staging = await blueprints.get_edge_model(
            self.graph,
            'Project',
            'Environment',
            'DEPLOYED_IN',
            context={'environment': 'staging'},
        )
        self.assertNotIn('deploy_tag', result_staging.model_fields)
