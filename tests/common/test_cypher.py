"""Tests for the cypher query generation module."""

import unittest

from imbi_common import cypher, models


def _org(slug: str = 'acme') -> models.Organization:
    return models.Organization(name='Acme', slug=slug)


def _team(slug: str = 'backend') -> models.Team:
    # model_construct bypasses validation — Edge fields accept
    # Node instances only when built from raw graph data (dicts).
    return models.Team.model_construct(
        name='Backend',
        slug=slug,
        organization=_org(),
    )


def _env(slug: str = 'production') -> models.Environment:
    return models.Environment.model_construct(
        name='Production',
        slug=slug,
        sort_order=1,
        organization=_org(),
    )


def _project_type(slug: str = 'web-app') -> models.ProjectType:
    return models.ProjectType.model_construct(
        name='Web App',
        slug=slug,
        organization=_org(),
    )


def _project() -> models.Project:
    return models.Project.model_construct(
        id='test-id',
        name='My Project',
        slug='my-project',
        team=_team(),
        project_types=[_project_type()],
        environments=[_env()],
        links={},
    )


class LabelTests(unittest.TestCase):
    def test_from_instance(self) -> None:
        self.assertEqual('Organization', cypher._label(_org()))

    def test_from_class(self) -> None:
        self.assertEqual('Team', cypher._label(models.Team))

    def test_subclass_name(self) -> None:
        self.assertEqual('Project', cypher._label(models.Project))


class NodePropertiesTests(unittest.TestCase):
    def test_organization_all_scalar(self) -> None:
        org = _org()
        props = cypher._node_properties(org)
        self.assertIn('name', props)
        self.assertIn('slug', props)
        self.assertNotIn('organization', props)

    def test_team_excludes_edge(self) -> None:
        team = _team()
        props = cypher._node_properties(team)
        self.assertIn('name', props)
        self.assertIn('slug', props)
        self.assertNotIn('organization', props)

    def test_project_excludes_all_edges(self) -> None:
        project = _project()
        props = cypher._node_properties(project)
        self.assertIn('id', props)
        self.assertIn('name', props)
        self.assertNotIn('team', props)
        self.assertNotIn('project_types', props)
        self.assertNotIn('environments', props)


class PropsTemplateTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual('', cypher._props_template({}))

    def test_single_key(self) -> None:
        result = cypher._props_template({'slug': 'x'})
        self.assertEqual('{{slug: {slug}}}', result)

    def test_multiple_keys(self) -> None:
        result = cypher._props_template(
            {'name': 'x', 'slug': 'y'},
        )
        self.assertIn('name: {name}', result)
        self.assertIn('slug: {slug}', result)
        self.assertTrue(result.startswith('{{'))
        self.assertTrue(result.endswith('}}'))


class EdgeFieldsTests(unittest.TestCase):
    def test_organization_has_no_edges(self) -> None:
        self.assertEqual([], cypher._edge_fields(models.Organization))

    def test_team_has_one_edge(self) -> None:
        edges = cypher._edge_fields(models.Team)
        self.assertEqual(1, len(edges))
        name, _, edge = edges[0]
        self.assertEqual('organization', name)
        self.assertEqual('BELONGS_TO', edge.rel_type)
        self.assertEqual('OUTGOING', edge.direction)

    def test_project_has_three_edges(self) -> None:
        edges = cypher._edge_fields(models.Project)
        self.assertEqual(3, len(edges))
        names = {e[0] for e in edges}
        self.assertEqual(
            {'team', 'project_types', 'environments'},
            names,
        )


class IsListEdgeTests(unittest.TestCase):
    def test_single_edge(self) -> None:
        info = models.Team.model_fields['organization']
        self.assertFalse(cypher._is_list_edge(info))

    def test_list_edge(self) -> None:
        info = models.Project.model_fields['project_types']
        self.assertTrue(cypher._is_list_edge(info))


class CreateTests(unittest.TestCase):
    def test_organization_single_statement(self) -> None:
        org = _org()
        stmts = cypher.create(org)
        self.assertEqual(1, len(stmts))
        self.assertIn('CREATE (n:Organization', stmts[0].cypher)
        self.assertIn('RETURN n', stmts[0].cypher)
        self.assertEqual('Acme', stmts[0].params['name'])
        self.assertEqual('acme', stmts[0].params['slug'])

    def test_team_creates_node_and_edge(self) -> None:
        team = _team()
        stmts = cypher.create(team)
        self.assertEqual(2, len(stmts))
        # First statement creates the node
        self.assertIn('CREATE (n:Team', stmts[0].cypher)
        # Second creates the BELONGS_TO edge
        self.assertIn('BELONGS_TO', stmts[1].cypher)
        self.assertIn('Organization', stmts[1].cypher)
        self.assertEqual('backend', stmts[1].params['src_slug'])
        self.assertEqual('acme', stmts[1].params['tgt_slug'])

    def test_project_creates_node_and_all_edges(self) -> None:
        project = _project()
        stmts = cypher.create(project)
        # 1 node + 1 team + 1 project_type + 1 environment
        self.assertEqual(4, len(stmts))
        self.assertIn('CREATE (n:Project', stmts[0].cypher)

    def test_empty_list_edge_skipped(self) -> None:
        project = models.Project.model_construct(
            id='test-id',
            name='Bare',
            slug='bare',
            team=_team(),
            project_types=[],
            environments=[],
            links={},
        )
        stmts = cypher.create(project)
        # 1 node + 1 team edge (empty lists produce nothing)
        self.assertEqual(2, len(stmts))

    def test_outgoing_direction_arrow(self) -> None:
        team = _team()
        stmts = cypher.create(team)
        edge_cypher = stmts[1].cypher
        self.assertIn('-[r:BELONGS_TO]->', edge_cypher)

    def test_node_params_are_json_serialized(self) -> None:
        org = _org()
        stmts = cypher.create(org)
        # created_at should be a string (ISO format from mode='json')
        self.assertIsInstance(stmts[0].params['created_at'], str)


class DeleteTests(unittest.TestCase):
    def test_generates_detach_delete(self) -> None:
        org = _org()
        stmt = cypher.delete(org)
        self.assertIn('MATCH (n:Organization', stmt.cypher)
        self.assertIn('DETACH DELETE n', stmt.cypher)
        self.assertIn('RETURN n', stmt.cypher)
        self.assertEqual('acme', stmt.params['slug'])


class MatchTests(unittest.TestCase):
    def test_with_params(self) -> None:
        stmt = cypher.match(
            models.Organization,
            {'slug': 'acme'},
        )
        self.assertIn('MATCH (n:Organization', stmt.cypher)
        self.assertIn('slug: {slug}', stmt.cypher)
        self.assertEqual('acme', stmt.params['slug'])

    def test_no_params(self) -> None:
        stmt = cypher.match(models.Organization)
        self.assertEqual(
            'MATCH (n:Organization) RETURN n',
            stmt.cypher,
        )
        self.assertEqual({}, stmt.params)

    def test_empty_dict_params(self) -> None:
        stmt = cypher.match(models.Organization, {})
        self.assertEqual(
            'MATCH (n:Organization) RETURN n',
            stmt.cypher,
        )

    def test_order_by(self) -> None:
        stmt = cypher.match(
            models.Blueprint,
            {'enabled': True},
            order_by='priority',
        )
        self.assertTrue(
            stmt.cypher.endswith('ORDER BY n.priority'),
        )

    def test_non_node_model(self) -> None:
        stmt = cypher.match(models.Blueprint, {'type': 'Project'})
        self.assertIn('MATCH (n:Blueprint', stmt.cypher)


class MergeTests(unittest.TestCase):
    def test_default_match_on_slug(self) -> None:
        org = _org()
        stmts = cypher.merge(org)
        self.assertIn(
            'MERGE (n:Organization {{slug: {slug}}})',
            stmts[0].cypher,
        )

    def test_set_clause(self) -> None:
        org = _org()
        stmts = cypher.merge(org)
        self.assertIn(' SET ', stmts[0].cypher)
        self.assertIn('n.name = {name}', stmts[0].cypher)
        # slug should NOT appear in SET (it's the match key)
        self.assertNotIn('n.slug =', stmts[0].cypher)

    def test_set_excludes_created_at(self) -> None:
        org = _org()
        stmts = cypher.merge(org)
        # created_at should not appear in SET to preserve
        # original creation timestamp on existing nodes
        self.assertNotIn('created_at', stmts[0].cypher)

    def test_custom_match_on(self) -> None:
        project = _project()
        stmts = cypher.merge(project, match_on=['id'])
        self.assertIn(
            'MERGE (n:Project {{id: {id}}})',
            stmts[0].cypher,
        )
        self.assertNotIn('n.id =', stmts[0].cypher)

    def test_includes_edge_statements(self) -> None:
        team = _team()
        stmts = cypher.merge(team)
        self.assertEqual(2, len(stmts))
        self.assertIn('MERGE', stmts[0].cypher)
        self.assertIn('BELONGS_TO', stmts[1].cypher)

    def test_params_include_all_properties(self) -> None:
        org = _org()
        stmts = cypher.merge(org)
        self.assertIn('name', stmts[0].params)
        self.assertIn('slug', stmts[0].params)

    def test_return_clause(self) -> None:
        org = _org()
        stmts = cypher.merge(org)
        self.assertTrue(stmts[0].cypher.endswith('RETURN n'))

    def test_edge_uses_merge_not_create(self) -> None:
        team = _team()
        stmts = cypher.merge(team)
        edge_cypher = stmts[1].cypher
        self.assertIn('MERGE', edge_cypher)
        self.assertNotIn('CREATE', edge_cypher)

    def test_set_excludes_none_values(self) -> None:
        # Organization with default None fields (description, icon,
        # updated_at) should not have those in the SET clause to
        # avoid silently deleting existing graph properties.
        org = _org()
        stmts = cypher.merge(org)
        self.assertNotIn('n.description =', stmts[0].cypher)
        self.assertNotIn('n.icon =', stmts[0].cypher)
        self.assertNotIn('n.updated_at =', stmts[0].cypher)

    def test_set_includes_non_none_optional_fields(self) -> None:
        org = models.Organization(
            name='Acme',
            slug='acme',
            description='Test org',
        )
        stmts = cypher.merge(org)
        self.assertIn('n.description =', stmts[0].cypher)

    def test_invalid_match_on_raises(self) -> None:
        org = _org()
        with self.assertRaises(ValueError):
            cypher.merge(org, match_on=['nonexistent'])


class MatchValidationTests(unittest.TestCase):
    def test_invalid_param_raises(self) -> None:
        with self.assertRaises(ValueError):
            cypher.match(
                models.Organization,
                {'nonexistent': 'val'},
            )

    def test_invalid_order_by_raises(self) -> None:
        with self.assertRaises(ValueError):
            cypher.match(
                models.Organization,
                order_by='nonexistent',
            )

    def test_edge_field_rejected_as_param(self) -> None:
        with self.assertRaises(ValueError):
            cypher.match(
                models.Team,
                {'organization': 'acme'},
            )


class NoneEdgeTests(unittest.TestCase):
    def test_none_single_edge_skipped(self) -> None:
        team = models.Team.model_construct(
            name='Backend',
            slug='backend',
            organization=None,
        )
        stmts = cypher.create(team)
        # Only the node CREATE, no edge statement
        self.assertEqual(1, len(stmts))
