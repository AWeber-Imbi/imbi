import json
import pathlib
import typing
import unittest
from unittest import mock

from imbi.api import sbom
from imbi.common import graph

_FIXTURE_DIR = pathlib.Path(__file__).parent / 'fixtures' / 'sbom'


def _load(name: str) -> dict[str, typing.Any]:
    return typing.cast(
        'dict[str, typing.Any]',
        json.loads((_FIXTURE_DIR / name).read_text()),
    )


def _tiny() -> dict[str, typing.Any]:
    return _load('tiny.json')


class SpecVersionTests(unittest.TestCase):
    def test_accepts_1_7(self) -> None:
        components = sbom.parse(_tiny())
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].name, 'express')

    def test_rejects_1_5(self) -> None:
        payload = _tiny()
        payload['specVersion'] = '1.5'
        with self.assertRaises(sbom.UnsupportedSpecVersionError) as ctx:
            sbom.parse(payload)
        self.assertEqual(ctx.exception.received, '1.5')

    def test_rejects_1_6(self) -> None:
        payload = _tiny()
        payload['specVersion'] = '1.6'
        with self.assertRaises(sbom.UnsupportedSpecVersionError):
            sbom.parse(payload)

    def test_rejects_missing_spec_version(self) -> None:
        payload = _tiny()
        del payload['specVersion']
        with self.assertRaises(sbom.UnsupportedSpecVersionError) as ctx:
            sbom.parse(payload)
        self.assertIsNone(ctx.exception.received)


class MalformedPayloadTests(unittest.TestCase):
    def test_rejects_non_object(self) -> None:
        with self.assertRaises(sbom.MalformedSBomError):
            sbom.parse('not a dict')

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(sbom.MalformedSBomError):
            sbom.parse(
                {
                    'specVersion': '1.7',
                    'bomFormat': 'CycloneDX',
                    'components': 'oops',
                },
            )


class ComponentExtractionTests(unittest.TestCase):
    def test_tiny_component(self) -> None:
        [component] = sbom.parse(_tiny())
        self.assertEqual(component.purl_name, 'pkg:npm/express')
        self.assertEqual(component.name, 'express')
        self.assertEqual(component.ecosystem, 'npm')
        self.assertEqual(component.version, '4.18.2')
        self.assertEqual(component.license, 'MIT')
        self.assertEqual(component.supplier, 'OpenJS Foundation')
        self.assertEqual(component.hashes, {'SHA-256': '0' * 64})

    def test_strips_purl_version(self) -> None:
        [component] = sbom.parse(_tiny())
        self.assertNotIn('@', component.purl_name)
        self.assertEqual(component.purl_name, 'pkg:npm/express')

    def test_strips_cpe_version(self) -> None:
        [component] = sbom.parse(_tiny())
        identifiers = {(i.kind, i.value) for i in component.identifiers}
        self.assertIn(
            ('cpe', 'cpe:2.3:a:expressjs:express:*:*:*:*:*:*:*:*'),
            identifiers,
        )

    def test_emits_purl_identifier(self) -> None:
        [component] = sbom.parse(_tiny())
        identifiers = {(i.kind, i.value) for i in component.identifiers}
        self.assertIn(('purl', 'pkg:npm/express'), identifiers)

    def test_skips_component_without_purl(self) -> None:
        payload = _tiny()
        payload['components'].append(
            {
                'type': 'library',
                'bom-ref': 'no-purl',
                'name': 'no-purl-library',
                'version': '1.0.0',
            },
        )
        components = sbom.parse(payload)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].name, 'express')


class DeduplicationTests(unittest.TestCase):
    def test_dedupes_duplicate_components(self) -> None:
        payload = _tiny()
        # Two entries for the same (purl_name, version) — e.g. a
        # transitive dependency reached via two paths.
        payload['components'].append(dict(payload['components'][0]))
        components = sbom.parse(payload)
        self.assertEqual(len(components), 1)

    def test_does_not_dedupe_distinct_versions(self) -> None:
        payload = _tiny()
        second = dict(payload['components'][0])
        second['version'] = '4.19.0'
        second['purl'] = 'pkg:npm/express@4.19.0'
        second['bom-ref'] = 'pkg:npm/express@4.19.0'
        payload['components'].append(second)
        components = sbom.parse(payload)
        versions = sorted(c.version for c in components)
        self.assertEqual(versions, ['4.18.2', '4.19.0'])


class LicenseTests(unittest.TestCase):
    def _component_with(
        self, licenses: list[dict[str, typing.Any]]
    ) -> sbom.NormalizedComponent:
        payload = _tiny()
        payload['components'][0]['licenses'] = licenses
        [component] = sbom.parse(payload)
        return component

    def test_license_id(self) -> None:
        component = self._component_with([{'license': {'id': 'MIT'}}])
        self.assertEqual(component.license, 'MIT')

    def test_license_expression(self) -> None:
        component = self._component_with([{'expression': 'MIT OR Apache-2.0'}])
        self.assertEqual(component.license, 'MIT OR Apache-2.0')

    def test_license_freeform_name(self) -> None:
        component = self._component_with(
            [{'license': {'name': 'Some Custom EULA'}}],
        )
        self.assertEqual(component.license, 'Some Custom EULA')

    def test_license_absent(self) -> None:
        payload = _tiny()
        del payload['components'][0]['licenses']
        [component] = sbom.parse(payload)
        self.assertIsNone(component.license)

    def test_license_multiple_records_joined(self) -> None:
        # The cyclonedx LicenseRepository is a SortedSet, so input
        # order is not preserved — assert on membership and the
        # joiner, not on order.
        component = self._component_with(
            [
                {'license': {'id': 'MIT'}},
                {'license': {'id': 'Apache-2.0'}},
            ],
        )
        self.assertIsNotNone(component.license)
        assert component.license is not None
        parts = component.license.split(' AND ')
        self.assertEqual(set(parts), {'MIT', 'Apache-2.0'})


class RealisticFixtureTests(unittest.TestCase):
    def test_npm_fixture(self) -> None:
        components = sbom.parse(_load('npm-realistic.json'))
        by_name = {c.name: c for c in components}
        self.assertEqual(
            set(by_name), {'react', 'react-dom', '@babel/runtime', 'lodash'}
        )
        self.assertEqual(by_name['react'].ecosystem, 'npm')
        self.assertEqual(by_name['react'].version, '18.3.1')
        self.assertEqual(
            by_name['@babel/runtime'].purl_name,
            'pkg:npm/%40babel/runtime',
        )

    def test_pypi_fixture(self) -> None:
        components = sbom.parse(_load('pypi-realistic.json'))
        by_name = {c.name: c for c in components}
        self.assertEqual(
            set(by_name),
            {'fastapi', 'pydantic', 'httpx', 'cryptography'},
        )
        self.assertEqual(by_name['fastapi'].ecosystem, 'pypi')
        self.assertEqual(by_name['fastapi'].supplier, 'Sebastián Ramírez')
        self.assertEqual(
            by_name['cryptography'].license, 'Apache-2.0 OR BSD-3-Clause'
        )

    def test_pypi_fixture_emits_purl_identifier(self) -> None:
        components = sbom.parse(_load('pypi-realistic.json'))
        by_name = {c.name: c for c in components}
        identifiers = {i.value for i in by_name['fastapi'].identifiers}
        self.assertIn('pkg:pypi/fastapi', identifiers)


class ScopeAndGroupsTests(unittest.TestCase):
    """``component.scope`` + ``cdx:pyproject:group`` extraction.

    These two fields are the cdxgen-specific signals Imbi keys on
    to populate the ``Release-[:USES_COMPONENT_RELEASE]->`` edge
    with ``ReleaseComponentEdge.scope`` and ``.groups`` (see
    ADR 0015 and plans/sbom-ingest.md).
    """

    def _with(
        self, **component_overrides: typing.Any
    ) -> sbom.NormalizedComponent:
        payload = _tiny()
        payload['components'][0].update(component_overrides)
        [component] = sbom.parse(payload)
        return component

    def test_scope_default_is_none(self) -> None:
        # cyclonedx-py emits no scope; cdxgen for runtime deps also
        # omits it. ``None`` (rather than defaulted "required") lets
        # the UI render an "unstated" cell distinct from explicit
        # required.
        component = self._with()
        self.assertIsNone(component.scope)

    def test_scope_required_round_trips(self) -> None:
        component = self._with(scope='required')
        self.assertEqual(component.scope, 'required')

    def test_scope_optional_round_trips(self) -> None:
        # cdxgen for uv/Poetry dev groups + npm devDependencies.
        component = self._with(scope='optional')
        self.assertEqual(component.scope, 'optional')

    def test_scope_excluded_round_trips(self) -> None:
        component = self._with(scope='excluded')
        self.assertEqual(component.scope, 'excluded')

    def test_groups_default_empty(self) -> None:
        component = self._with()
        self.assertEqual(component.groups, [])

    def test_groups_captured_from_cdx_pyproject_group(self) -> None:
        # The cdxgen Python branch emits one property per group the
        # package was attributed to (PEP 735 + Poetry). Imbi must
        # capture every entry.
        component = self._with(
            scope='optional',
            properties=[
                {'name': 'cdx:pyproject:group', 'value': 'dev'},
                {'name': 'cdx:pyproject:group', 'value': 'test'},
            ],
        )
        self.assertEqual(component.scope, 'optional')
        self.assertEqual(component.groups, ['dev', 'test'])

    def test_groups_sorted_and_deduplicated(self) -> None:
        # Producer-side duplication or random order shouldn't be
        # observable in the graph — equality comparisons across
        # releases must stay stable.
        component = self._with(
            properties=[
                {'name': 'cdx:pyproject:group', 'value': 'test'},
                {'name': 'cdx:pyproject:group', 'value': 'dev'},
                {'name': 'cdx:pyproject:group', 'value': 'dev'},
            ],
        )
        self.assertEqual(component.groups, ['dev', 'test'])

    def test_groups_ignore_non_allowlisted_properties(self) -> None:
        # cdxgen also emits properties like
        # ``cdx:npm:package:development`` (a boolean flag, not a
        # group name) and ``cdx:python:package:required-extra``.
        # Neither belongs in ``groups`` — only allow-listed
        # property names contribute.
        component = self._with(
            properties=[
                {'name': 'cdx:npm:package:development', 'value': 'true'},
                {
                    'name': 'cdx:python:package:required-extra',
                    'value': 'dev',
                },
                {'name': 'cdx:pyproject:group', 'value': 'real-group'},
            ],
        )
        self.assertEqual(component.groups, ['real-group'])

    def test_empty_group_value_skipped(self) -> None:
        component = self._with(
            properties=[
                {'name': 'cdx:pyproject:group', 'value': ''},
                {'name': 'cdx:pyproject:group', 'value': 'dev'},
            ],
        )
        self.assertEqual(component.groups, ['dev'])


class DualWriteTests(unittest.IsolatedAsyncioTestCase):
    """`replace_release_components` records the set in both stores."""

    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.db.execute.return_value = [
            {'component_id': '"c-1"', 'component_release_id': '"cr-1"'}
        ]
        self.insert = mock.AsyncMock()
        patcher = mock.patch('imbi.common.clickhouse.insert', self.insert)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _component(**overrides: typing.Any) -> sbom.NormalizedComponent:
        data: dict[str, typing.Any] = {
            'purl_name': 'pkg:pypi/requests',
            'name': 'requests',
            'ecosystem': 'pypi',
            'version': '2.32.0',
            'scope': 'required',
            'groups': ['runtime'],
        }
        data.update(overrides)
        return sbom.NormalizedComponent(**data)

    def _writes(self) -> dict[str, list]:
        """Map each written table to its rows, in call order."""
        return {
            call.args[0]: call.args[1] for call in self.insert.await_args_list
        }

    def _batch(self) -> typing.Any:
        (batch,) = self._writes()['release_component_batches']
        return batch

    def _facts(self) -> list:
        return self._writes().get('release_components', [])

    async def test_row_written_for_each_component(self) -> None:
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', [self._component()]
        )
        (row,) = self._facts()
        self.assertEqual(row.release_id, 'r-1')
        self.assertEqual(row.project_id, 'p-1')
        self.assertEqual(row.component_id, 'c-1')
        self.assertEqual(row.component_release_id, 'cr-1')
        self.assertEqual(row.purl_name, 'pkg:pypi/requests')
        self.assertEqual(row.ecosystem, 'pypi')
        self.assertEqual(row.version, '2.32.0')
        self.assertEqual(row.scope, 'required')
        self.assertEqual(row.groups, ['runtime'])

    async def test_ids_come_from_the_graph_not_the_generated_nanoids(
        self,
    ) -> None:
        """MERGE keeps the existing id, so the generated one is a decoy."""
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', [self._component()]
        )
        (row,) = self._facts()
        self.assertEqual(
            (row.component_id, row.component_release_id), ('c-1', 'cr-1')
        )

    async def test_facts_are_written_before_the_batch_publishes_them(
        self,
    ) -> None:
        """A reader must never resolve a batch to a half-written set."""
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', [self._component()]
        )
        self.assertEqual(
            [call.args[0] for call in self.insert.await_args_list],
            ['release_components', 'release_component_batches'],
        )

    async def test_one_batch_id_and_timestamp_across_the_ingest(self) -> None:
        components = [
            self._component(purl_name=f'pkg:pypi/pkg-{n}', name=f'pkg-{n}')
            for n in range(5)
        ]
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', components
        )
        rows = self._facts()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({row.recorded_at for row in rows}), 1)
        self.assertEqual(
            {row.batch_id for row in rows}, {self._batch().batch_id}
        )
        self.assertEqual(self._batch().recorded_at, rows[0].recorded_at)

    async def test_batch_defaults_to_the_ingest_source(self) -> None:
        """Backfill loses the tiebreak to a live write, so this matters."""
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', [self._component()]
        )
        self.assertEqual(self._batch().source, 'ingest')

    async def test_failed_component_writes_no_row_but_is_counted(
        self,
    ) -> None:
        """A short snapshot must be detectable, not silently complete."""
        self.db.execute.side_effect = [
            [],  # the clear
            RuntimeError('AGE said no'),
            [{'component_id': '"c-2"', 'component_release_id': '"cr-2"'}],
        ]
        await sbom.replace_release_components(
            self.db,
            'p-1',
            'r-1',
            [
                self._component(purl_name='pkg:pypi/broken', name='broken'),
                self._component(purl_name='pkg:pypi/fine', name='fine'),
            ],
        )
        self.assertEqual([row.component_id for row in self._facts()], ['c-2'])
        self.assertEqual(self._batch().component_count, 1)
        self.assertEqual(self._batch().parsed_count, 2)

    async def test_complete_ingest_has_matching_counts(self) -> None:
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', [self._component()]
        )
        self.assertEqual(
            self._batch().component_count, self._batch().parsed_count
        )

    async def test_empty_sbom_publishes_an_empty_batch(self) -> None:
        """Without one the previous batch stays current forever."""
        await sbom.replace_release_components(self.db, 'p-1', 'r-1', [])
        self.assertNotIn('release_components', self._writes())
        batch = self._batch()
        self.assertEqual(batch.release_id, 'r-1')
        self.assertEqual(batch.component_count, 0)
        self.assertEqual(batch.parsed_count, 0)

    async def test_all_components_failing_publishes_an_empty_batch(
        self,
    ) -> None:
        self.db.execute.side_effect = [[], RuntimeError('AGE said no')]
        await sbom.replace_release_components(
            self.db, 'p-1', 'r-1', [self._component()]
        )
        self.assertEqual(self._batch().component_count, 0)
        self.assertEqual(self._batch().parsed_count, 1)

    async def test_clickhouse_failure_propagates(self) -> None:
        """A dropped write is missing report data, not a partial one."""
        self.insert.side_effect = RuntimeError('clickhouse unreachable')
        with self.assertRaises(RuntimeError):
            await sbom.replace_release_components(
                self.db, 'p-1', 'r-1', [self._component()]
            )

    async def test_unpublished_facts_when_the_batch_write_fails(self) -> None:
        """The rows land, stay inert, and the request still fails."""
        self.insert.side_effect = [mock.DEFAULT, RuntimeError('no batch')]
        with self.assertRaises(RuntimeError):
            await sbom.replace_release_components(
                self.db, 'p-1', 'r-1', [self._component()]
            )
        self.assertEqual(
            [call.args[0] for call in self.insert.await_args_list],
            ['release_components', 'release_component_batches'],
        )
