"""Tests for the CVE catalog import, lookup, and advisory enrichment."""

import datetime
import io
import pathlib
import tempfile
import typing
import unittest
import zipfile
from unittest import mock

import fastapi
import httpx
import orjson
import respx

from imbi.api import cves
from imbi.api.endpoints import components
from imbi.api.maintenance import log, operations

UTC = datetime.UTC
TAG = 'cve_2026-11-13_0100Z'
DOWNLOAD_URL = 'https://github.com/CVEProject/cvelistV5/releases/download/x'


def _record(
    cve_id: str = 'CVE-2025-0001',
    *,
    updated: str | None = '2025-02-01T10:00:00.123456Z',
    published: str | None = '2025-01-01T00:00:00.000Z',
    reserved: str | None = '2024-12-01T00:00:00.000Z',
    title: str | None = 'Remote code execution',
    descriptions: list[dict[str, str]] | None = None,
    cna_metrics: list[dict[str, typing.Any]] | None = None,
    adp: list[dict[str, typing.Any]] | None = None,
) -> dict[str, typing.Any]:
    meta: dict[str, typing.Any] = {
        'cveId': cve_id,
        'state': 'PUBLISHED',
        'assignerShortName': 'apache',
    }
    for key, value in (
        ('dateUpdated', updated),
        ('datePublished', published),
        ('dateReserved', reserved),
    ):
        if value is not None:
            meta[key] = value
    cna: dict[str, typing.Any] = {
        'descriptions': descriptions
        if descriptions is not None
        else [
            {'lang': 'fr', 'value': 'Exécution de code'},
            {'lang': 'en', 'value': 'A crafted request runs code.'},
        ],
        'metrics': cna_metrics or [],
        'problemTypes': [
            {'descriptions': [{'cweId': 'CWE-94'}, {'cweId': 'CWE-94'}]}
        ],
        'references': [{'url': 'https://example.com/a'}, {'name': 'x'}],
    }
    if title is not None:
        cna['title'] = title
    return {
        'cveMetadata': meta,
        'containers': {'cna': cna, 'adp': adp or []},
    }


def _cvss(key: str, score: float, severity: str | None = None) -> dict:
    metric: dict[str, typing.Any] = {
        'baseScore': score,
        'vectorString': f'{key}/{score}',
    }
    if severity is not None:
        metric['baseSeverity'] = severity
    return {key: metric}


def _inner_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('cves/', b'')
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _outer_zip(inner: bytes) -> bytes:
    """The release asset: a zip whose one member is ``cves.zip``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('cves.zip', inner)
    return buffer.getvalue()


def _files(*records: dict[str, typing.Any]) -> dict[str, bytes]:
    return {
        f'cves/2025/0xxx/{r["cveMetadata"]["cveId"]}.json': orjson.dumps(r)
        for r in records
    }


class ParseRecordTests(unittest.TestCase):
    def test_reads_the_cna_fields(self) -> None:
        record = cves.parse_record(
            _record(cna_metrics=[_cvss('cvssV3_1', 9.8, 'CRITICAL')])
        )
        assert record is not None
        self.assertEqual('CVE-2025-0001', record.cve_id)
        self.assertEqual('PUBLISHED', record.state)
        self.assertEqual('apache', record.assigner)
        self.assertEqual('Remote code execution', record.title)
        self.assertEqual('A crafted request runs code.', record.description)
        self.assertEqual(9.8, record.cvss_score)
        self.assertEqual('CRITICAL', record.cvss_severity)
        self.assertEqual('cvssV3_1/9.8', record.cvss_vector)
        self.assertEqual(['CWE-94'], record.cwe_ids)
        self.assertEqual(['https://example.com/a'], record.references)
        self.assertEqual(
            datetime.datetime(2025, 1, 1, tzinfo=UTC), record.published_at
        )

    def test_cuts_updated_at_to_milliseconds(self) -> None:
        # The table stores milliseconds; microseconds would make every
        # daily run publish the record again.
        record = cves.parse_record(_record())
        assert record is not None
        self.assertEqual(
            datetime.datetime(2025, 2, 1, 10, 0, 0, 123000, tzinfo=UTC),
            record.updated_at,
        )

    def test_updated_at_falls_back_to_published_then_reserved(self) -> None:
        record = cves.parse_record(_record(updated=None))
        assert record is not None
        self.assertEqual(
            datetime.datetime(2025, 1, 1, tzinfo=UTC), record.updated_at
        )
        record = cves.parse_record(_record(updated=None, published=None))
        assert record is not None
        self.assertEqual(
            datetime.datetime(2024, 12, 1, tzinfo=UTC), record.updated_at
        )
        self.assertIsNone(record.published_at)

    def test_no_date_or_no_id_is_no_record(self) -> None:
        self.assertIsNone(
            cves.parse_record(
                _record(updated=None, published=None, reserved=None)
            )
        )
        self.assertIsNone(cves.parse_record(_record(cve_id='')))
        self.assertIsNone(cves.parse_record(['not', 'a', 'record']))

    def test_title_falls_back_to_the_description(self) -> None:
        long = 'x' * 500
        record = cves.parse_record(
            _record(title=None, descriptions=[{'lang': 'en', 'value': long}])
        )
        assert record is not None
        self.assertEqual(cves.TITLE_LENGTH, len(record.title))
        self.assertTrue(record.title.endswith('…'))
        self.assertEqual(long, record.description)

    def test_takes_the_highest_cvss_from_cna_and_adp(self) -> None:
        record = cves.parse_record(
            _record(
                cna_metrics=[_cvss('cvssV3_1', 5.3, 'MEDIUM')],
                adp=[{'metrics': [{'other': {}}, _cvss('cvssV4_0', 8.7)]}],
            )
        )
        assert record is not None
        self.assertEqual(8.7, record.cvss_score)
        # No baseSeverity: the rating comes from the score.
        self.assertEqual('HIGH', record.cvss_severity)
        self.assertEqual('cvssV4_0/8.7', record.cvss_vector)

    def test_no_cvss_is_null(self) -> None:
        record = cves.parse_record(_record())
        assert record is not None
        self.assertIsNone(record.cvss_score)
        self.assertIsNone(record.cvss_severity)
        self.assertIsNone(record.cvss_vector)


class ChangedBatchesTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = pathlib.Path(tmp.name) / 'cves.zip'

    def _write(self, files: dict[str, bytes]) -> None:
        self.path.write_bytes(_inner_zip(files))

    def test_skips_records_the_table_has_at_the_same_version(self) -> None:
        self._write(
            _files(
                _record('CVE-2025-0001'),
                _record('CVE-2025-0002'),
                _record('CVE-2025-0003'),
            )
        )
        same = datetime.datetime(2025, 2, 1, 10, 0, 0, 123000, tzinfo=UTC)
        existing = {
            'CVE-2025-0001': same,
            'CVE-2025-0002': same - datetime.timedelta(seconds=1),
        }
        counter = [0]
        batches = list(cves.changed_batches(self.path, existing, counter))
        self.assertEqual(3, counter[0])
        self.assertEqual(
            ['CVE-2025-0002', 'CVE-2025-0003'],
            sorted(r.cve_id for batch in batches for r in batch),
        )

    def test_yields_batches_of_the_given_size(self) -> None:
        self._write(_files(*(_record(f'CVE-2025-000{i}') for i in range(5))))
        sizes = [
            len(batch) for batch in cves.changed_batches(self.path, {}, [0], 2)
        ]
        self.assertEqual([2, 2, 1], sizes)

    def test_skips_files_that_are_not_records(self) -> None:
        files = _files(_record('CVE-2025-0001'))
        files['cves/2025/0xxx/CVE-2025-0002.json'] = b'{not json'
        files['cves/delta.json'] = b'{}'
        self._write(files)
        counter = [0]
        batches = list(cves.changed_batches(self.path, {}, counter))
        self.assertEqual(2, counter[0])
        self.assertEqual(
            ['CVE-2025-0001'], [r.cve_id for b in batches for r in b]
        )


class ImportReleaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.asset_bytes = _outer_zip(
            _inner_zip(
                _files(_record('CVE-2025-0001'), _record('CVE-2025-0002'))
            )
        )
        query = mock.patch(
            'imbi.common.clickhouse.query',
            new_callable=mock.AsyncMock,
            return_value=[
                {
                    'cve_id': 'CVE-2025-0001',
                    # ClickHouse returns naive UTC.
                    'updated_at': datetime.datetime(
                        2025, 2, 1, 10, 0, 0, 123000, tzinfo=UTC
                    ).replace(tzinfo=None),
                }
            ],
        )
        self.query = query.start()
        self.addCleanup(query.stop)
        publish = mock.patch(
            'imbi.common.iggy.publish', new_callable=mock.AsyncMock
        )
        self.publish = publish.start()
        self.addCleanup(publish.stop)

    def _release(self, size: int | None = None) -> None:
        respx.get(f'{cves.RELEASES_URL}/tags/{TAG}').respond(
            json={
                'tag_name': TAG,
                'assets': [
                    {'name': 'delta.zip', 'size': 1},
                    {
                        'name': '2026-11-13_all_CVEs_at_midnight.zip.zip',
                        'size': size or len(self.asset_bytes),
                        'browser_download_url': DOWNLOAD_URL,
                    },
                ],
            }
        )
        respx.get(DOWNLOAD_URL).respond(content=self.asset_bytes)

    @respx.mock
    async def test_publishes_only_changed_records(self) -> None:
        self._release()
        async with cves.http_client() as client:
            result = await cves.import_release(client, TAG)
        self.assertEqual(cves.ImportResult(records=2, published=1), result)
        stream, topic, rows = self.publish.await_args.args
        self.assertEqual(('cves', 'maintenance'), (stream, topic))
        self.assertEqual(['CVE-2025-0002'], [r.cve_id for r in rows])

    @respx.mock
    async def test_a_size_mismatch_fails(self) -> None:
        self._release(size=len(self.asset_bytes) + 1)
        async with cves.http_client() as client:
            with self.assertRaisesRegex(cves.ImportFailed, 'expected'):
                await cves.import_release(client, TAG)
        self.publish.assert_not_awaited()

    @respx.mock
    async def test_a_release_with_no_midnight_asset_fails(self) -> None:
        respx.get(f'{cves.RELEASES_URL}/tags/{TAG}').respond(
            json={'tag_name': TAG, 'assets': [{'name': 'delta.zip'}]}
        )
        async with cves.http_client() as client:
            with self.assertRaisesRegex(cves.ImportFailed, 'no _all_CVEs'):
                await cves.import_release(client, TAG)

    @respx.mock
    async def test_latest_release_tag(self) -> None:
        respx.get(f'{cves.RELEASES_URL}/latest').respond(
            json={'tag_name': TAG}
        )
        async with cves.http_client() as client:
            self.assertEqual(TAG, await cves.latest_release_tag(client))


class LookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_all_ids_in_one_query(self) -> None:
        row = {
            'cve_id': 'CVE-2025-0001',
            'state': 'PUBLISHED',
            'assigner': 'apache',
            'published_at': None,
            'updated_at': datetime.datetime(2025, 2, 1, tzinfo=UTC).replace(
                tzinfo=None
            ),
            'title': 't',
            'description': 'd',
            'cvss_score': 7.5,
            'cvss_severity': 'HIGH',
            'cvss_vector': None,
            'cwe_ids': [],
            'references': [],
        }
        with mock.patch(
            'imbi.common.clickhouse.query',
            new_callable=mock.AsyncMock,
            return_value=[row],
        ) as query:
            found = await cves.lookup({'CVE-2025-0002', 'CVE-2025-0001'})
        query.assert_awaited_once()
        self.assertIn('FINAL', query.await_args.args[0])
        self.assertEqual(
            {'cve_ids': ['CVE-2025-0001', 'CVE-2025-0002']},
            query.await_args.kwargs['tables'],
        )
        self.assertEqual(['CVE-2025-0001'], list(found))
        self.assertEqual(UTC, found['CVE-2025-0001'].updated_at.tzinfo)

    async def test_no_ids_is_no_query(self) -> None:
        with mock.patch(
            'imbi.common.clickhouse.query', new_callable=mock.AsyncMock
        ) as query:
            self.assertEqual({}, await cves.lookup([]))
        query.assert_not_awaited()


def _catalog_record(cve_id: str) -> cves.CveRecord:
    return cves.CveRecord(
        cve_id=cve_id,
        state='PUBLISHED',
        updated_at=datetime.datetime(2025, 2, 1, tzinfo=UTC),
        published_at=datetime.datetime(2025, 1, 1, tzinfo=UTC),
        title='Catalog title',
        description='Catalog description',
        cvss_score=9.8,
        cvss_severity='CRITICAL',
    )


class EnrichTests(unittest.IsolatedAsyncioTestCase):
    def _advisories(self) -> list[components.AdvisoryResponse]:
        return [
            components.AdvisoryResponse(cve_id=cve_id, url='https://x')
            for cve_id in ('CVE-2025-0001', 'CVE-2025-0002', 'CVE-2025-0001')
        ]

    async def test_one_batched_lookup_fills_the_catalog_fields(self) -> None:
        advisories = self._advisories()
        with mock.patch.object(
            cves,
            'lookup',
            mock.AsyncMock(
                return_value={
                    'CVE-2025-0001': _catalog_record('CVE-2025-0001')
                }
            ),
        ) as lookup:
            await components._enrich(advisories)
        lookup.assert_awaited_once_with(['CVE-2025-0001', 'CVE-2025-0002'])
        first, missing, _ = advisories
        self.assertEqual('CRITICAL', first.severity)
        self.assertEqual(9.8, first.cvss_score)
        self.assertEqual('Catalog description', first.description)
        self.assertEqual(
            datetime.datetime(2025, 1, 1, tzinfo=UTC), first.published_at
        )
        self.assertTrue(first.in_catalog)
        self.assertFalse(missing.in_catalog)
        self.assertIsNone(missing.severity)

    async def test_a_clickhouse_failure_omits_the_fields(self) -> None:
        advisories = self._advisories()
        with mock.patch(
            'imbi.common.clickhouse.query',
            new_callable=mock.AsyncMock,
            side_effect=RuntimeError('Failed to initialize ClickHouse'),
        ):
            await components._enrich(advisories)
        for advisory in advisories:
            self.assertIsNone(advisory.in_catalog)
            self.assertIsNone(advisory.severity)
            self.assertIsNone(advisory.description)

    async def test_no_advisories_is_no_lookup(self) -> None:
        with mock.patch.object(cves, 'lookup', mock.AsyncMock()) as lookup:
            await components._enrich([])
        lookup.assert_not_awaited()


def _ctx() -> log.MaintenanceContext:
    return log.MaintenanceContext(
        run_id='run1',
        attempt_id='attempt1',
        item_id=TAG,
        project_id='',
        project_slug='',
        log=log.ItemLog('cve-sync', 'run1', 'attempt1', TAG),
    )


class CveSyncOperationTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, **patch: typing.Any) -> str:
        with mock.patch.object(cves, 'import_release', **patch):
            return await operations.execute_cve_sync(
                mock.AsyncMock(), mock.AsyncMock(), TAG, ctx=self.ctx
            )

    def setUp(self) -> None:
        self.ctx = _ctx()

    async def test_records_what_it_published(self) -> None:
        outcome = await self._run(
            return_value=cves.ImportResult(records=10, published=3)
        )
        self.assertEqual('succeeded', outcome)
        (row,) = self.ctx.log.rows
        self.assertEqual(3, row.detail['published'])
        self.assertEqual(TAG, row.detail['release'])

    async def test_an_import_failure_fails_the_item(self) -> None:
        with self.assertRaisesRegex(
            operations.MaintenanceItemFailed, 'no asset'
        ):
            await self._run(side_effect=cves.ImportFailed('no asset'))

    async def test_a_download_failure_fails_the_item(self) -> None:
        with self.assertRaisesRegex(
            operations.MaintenanceItemFailed, 'download failed'
        ):
            await self._run(side_effect=httpx.ConnectError('refused'))

    @respx.mock
    async def test_enumerates_the_latest_release(self) -> None:
        respx.get(f'{cves.RELEASES_URL}/latest').respond(
            json={'tag_name': TAG}
        )
        self.assertEqual(
            [TAG], await operations.enumerate_cve_release(mock.AsyncMock())
        )

    @respx.mock
    async def test_a_github_failure_at_enumeration_is_a_502(self) -> None:
        respx.get(f'{cves.RELEASES_URL}/latest').respond(status_code=503)
        with self.assertRaises(fastapi.HTTPException) as caught:
            await operations.enumerate_cve_release(mock.AsyncMock())
        self.assertEqual(502, caught.exception.status_code)
