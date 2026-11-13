"""The CVE catalog: import from the CVE List, and lookup.

The ``cve-sync`` maintenance operation imports the CVE List
(CVEProject/cvelistV5) into the ClickHouse ``cves`` table each day. Each
GitHub release of the CVE List has an ``_all_CVEs_at_midnight`` asset: a
zip that holds one member, ``cves.zip``, which holds one JSON file for
each CVE record (CVE JSON 5.x).

The import streams both zips to temporary files and never holds them in
memory. Before it parses, it reads the newest ``updated_at`` of each CVE
that the table has, and it publishes only the records that are newer.
Thus a daily run publishes only the records that changed that day.
Parsing runs in a thread, so the API event loop is not blocked.

Advisory responses read the catalog with :func:`lookup`.
"""

import asyncio
import datetime
import logging
import pathlib
import shutil
import tempfile
import typing
import zipfile
from collections import abc

import httpx
import orjson
import pydantic

from imbi.common import clickhouse, iggy

LOGGER = logging.getLogger(__name__)

LATEST_RELEASE_URL = (
    'https://api.github.com/repos/CVEProject/cvelistV5/releases/latest'
)

#: The release asset that holds every CVE record at midnight UTC.
ASSET_MARKER = '_all_CVEs_at_midnight'

#: The stream (and ClickHouse table) and the topic the import publishes to.
STREAM = 'cves'
TOPIC = 'maintenance'

#: Records published in one call.
BATCH_SIZE = 10_000

#: A title made from the description is cut to this length.
TITLE_LENGTH = 200

CVSS_KEYS = ('cvssV4_0', 'cvssV3_1', 'cvssV3_0', 'cvssV2_0')

_HEADERS = {'Accept': 'application/vnd.github+json'}


class CveRecord(pydantic.BaseModel):
    """One row of the ClickHouse ``cves`` table."""

    cve_id: str
    state: str
    assigner: str = ''
    published_at: datetime.datetime | None = None
    updated_at: datetime.datetime
    title: str = ''
    description: str = ''
    cvss_score: float | None = None
    cvss_severity: str | None = None
    cvss_vector: str | None = None
    cwe_ids: list[str] = []
    references: list[str] = []


class ImportResult(typing.NamedTuple):
    """What one import read and published."""

    release: str
    records: int
    published: int


# ----- Parsing ---------------------------------------------------------


def _timestamp(value: object) -> datetime.datetime | None:
    """Parse a CVE JSON date as UTC, cut to milliseconds.

    The table stores milliseconds, so a value with microseconds would
    never compare equal to the stored value and would be published
    again each day.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    parsed = parsed.astimezone(datetime.UTC)
    return parsed.replace(microsecond=parsed.microsecond // 1000 * 1000)


def _dict(value: object) -> dict[str, typing.Any]:
    """``value`` when it is a JSON object, else an empty one."""
    if isinstance(value, dict):
        return typing.cast('dict[str, typing.Any]', value)
    return {}


def _dicts(value: object) -> list[dict[str, typing.Any]]:
    """The JSON objects in ``value`` when it is a list, else none."""
    if not isinstance(value, list):
        return []
    return [
        typing.cast('dict[str, typing.Any]', item)
        for item in typing.cast('list[object]', value)
        if isinstance(item, dict)
    ]


def _text(value: object) -> str:
    """``value`` as stripped text; empty for anything but a string."""
    return value.strip() if isinstance(value, str) else ''


def _english(entries: object, key: str = 'value') -> str:
    """Return the first English ``key`` value in a list of entries."""
    for entry in _dicts(entries):
        if _text(entry.get('lang')).lower().startswith('en'):
            return _text(entry.get(key))
    return ''


def _severity(score: float) -> str:
    """The CVSS v3 rating for a score, for metrics that have none."""
    if score >= 9.0:
        return 'CRITICAL'
    if score >= 7.0:
        return 'HIGH'
    if score >= 4.0:
        return 'MEDIUM'
    if score > 0.0:
        return 'LOW'
    return 'NONE'


def _highest_cvss(
    containers: list[dict[str, typing.Any]],
) -> tuple[float | None, str | None, str | None]:
    """The highest CVSS score in the CNA and ADP metrics, with its
    severity and vector."""
    best: tuple[float | None, str | None, str | None] = (None, None, None)
    for container in containers:
        for metric in _dicts(container.get('metrics')):
            for key in CVSS_KEYS:
                cvss = _dict(metric.get(key))
                score: object = cvss.get('baseScore')
                if not isinstance(score, int | float):
                    continue
                if best[0] is not None and score <= best[0]:
                    continue
                severity = _text(cvss.get('baseSeverity')).upper()
                best = (
                    float(score),
                    severity or _severity(float(score)),
                    _text(cvss.get('vectorString')) or None,
                )
    return best


def _unique(values: abc.Iterable[str]) -> list[str]:
    """The non-empty ``values`` in order, without repeats."""
    return list(dict.fromkeys(value for value in values if value))


def parse_record(data: object) -> CveRecord | None:
    """Build a row from one CVE JSON 5.x record.

    Returns ``None`` for a record with no CVE ID or no date at all.
    ``updated_at`` falls back to ``datePublished``, then
    ``dateReserved``. The title falls back to the description, cut to
    :data:`TITLE_LENGTH`.
    """
    record = _dict(data)
    meta = _dict(record.get('cveMetadata'))
    cve_id = normalize(_text(meta.get('cveId')))
    published_at = _timestamp(meta.get('datePublished'))
    updated_at = (
        _timestamp(meta.get('dateUpdated'))
        or published_at
        or _timestamp(meta.get('dateReserved'))
    )
    if not cve_id or updated_at is None:
        return None
    raw = _dict(record.get('containers'))
    cna = _dict(raw.get('cna'))
    containers = [cna, *_dicts(raw.get('adp'))]
    description = _english(cna.get('descriptions')) or _english(
        cna.get('rejectedReasons')
    )
    title = _text(cna.get('title'))
    if not title and description:
        title = description.split('\n', 1)[0]
        if len(title) > TITLE_LENGTH:
            title = title[: TITLE_LENGTH - 1].rstrip() + '…'
    score, severity, vector = _highest_cvss(containers)
    return CveRecord(
        cve_id=cve_id,
        state=_text(meta.get('state')),
        assigner=_text(meta.get('assignerShortName')),
        published_at=published_at,
        updated_at=updated_at,
        title=title,
        description=description,
        cvss_score=score,
        cvss_severity=severity,
        cvss_vector=vector,
        cwe_ids=_unique(
            _text(entry.get('cweId'))
            for container in containers
            for problem in _dicts(container.get('problemTypes'))
            for entry in _dicts(problem.get('descriptions'))
        ),
        references=_unique(
            _text(reference.get('url'))
            for reference in _dicts(cna.get('references'))
        ),
    )


def normalize(cve_id: str) -> str:
    """The canonical (trimmed, upper-case) form of a CVE ID."""
    return cve_id.strip().upper()


def _epoch_ms(value: datetime.datetime) -> int:
    """``value`` as whole milliseconds since the epoch."""
    return (value - _EPOCH) // datetime.timedelta(milliseconds=1)


_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)


def changed_batches(
    path: pathlib.Path,
    existing: abc.Mapping[str, int],
    batch_size: int = BATCH_SIZE,
) -> abc.Iterator[tuple[list[CveRecord], int]]:
    """Yield the records in the inner zip that ``existing`` (CVE ID to
    ``updated_at`` in epoch milliseconds) does not have at the same or a
    newer version, in batches.

    Each item is ``(batch, records read so far)``. The last item has the
    total and can have an empty batch. A record that does not parse is
    logged and skipped: one bad file must not stop the import of the
    other 400 000.
    """
    batch: list[CveRecord] = []
    read = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.rsplit('/', 1)[-1]
            if not (name.startswith('CVE-') and name.endswith('.json')):
                continue
            read += 1
            try:
                record = parse_record(orjson.loads(archive.read(info)))
            except orjson.JSONDecodeError as err:
                LOGGER.warning('Skipped CVE file %s: %s', info.filename, err)
                continue
            if record is None:
                continue
            stored = existing.get(record.cve_id)
            if stored is not None and _epoch_ms(record.updated_at) <= stored:
                continue
            batch.append(record)
            if len(batch) >= batch_size:
                yield batch, read
                batch = []
    yield batch, read


# ----- Import ----------------------------------------------------------


class ImportFailed(Exception):
    """The import cannot continue; the message is safe to show."""


def _midnight_asset(release: dict[str, typing.Any]) -> dict[str, typing.Any]:
    for asset in _dicts(release.get('assets')):
        if ASSET_MARKER in _text(asset.get('name')):
            return asset
    raise ImportFailed(
        f'Release {release.get("tag_name")} has no {ASSET_MARKER} asset'
    )


async def _download(
    client: httpx.AsyncClient, asset: dict[str, typing.Any], path: pathlib.Path
) -> None:
    """Stream the asset to ``path`` and check its size."""
    async with client.stream(
        'GET', str(asset['browser_download_url']), follow_redirects=True
    ) as response:
        response.raise_for_status()
        with path.open('wb') as handle:
            async for chunk in response.aiter_bytes(1 << 20):
                await asyncio.to_thread(handle.write, chunk)
    size = path.stat().st_size
    if size != asset.get('size'):
        raise ImportFailed(
            f'Downloaded {size} bytes of {asset["name"]}, '
            f'expected {asset.get("size")}'
        )


def _extract_inner(outer: pathlib.Path, inner: pathlib.Path) -> None:
    """Copy the one zip member of ``outer`` to ``inner``."""
    with zipfile.ZipFile(outer) as archive:
        members = [
            info
            for info in archive.infolist()
            if info.filename.endswith('.zip')
        ]
        if len(members) != 1:
            raise ImportFailed(f'Expected one inner zip, found {len(members)}')
        with archive.open(members[0]) as src, inner.open('wb') as dst:
            shutil.copyfileobj(src, dst, 1 << 20)


async def stored_versions() -> dict[str, int]:
    """The newest ``updated_at`` of each CVE in the table, in epoch
    milliseconds. An int per CVE keeps the ~425 000-entry map small."""
    rows = await clickhouse.query(
        'SELECT cve_id, toUnixTimestamp64Milli(max(updated_at)) AS version'
        ' FROM imbi.cves GROUP BY cve_id'
    )
    return {str(row['cve_id']): int(row['version']) for row in rows}


async def import_latest() -> ImportResult:
    """Import the midnight snapshot of the newest CVE List release.

    Raises:
        ImportFailed: The release or its asset is not as expected.
        httpx.HTTPError: A GitHub request failed.
        iggy.PublishError: A publish failed. Records published before
            it stay; the next run publishes the rest.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(LATEST_RELEASE_URL, headers=_HEADERS)
        response.raise_for_status()
        release = _dict(response.json())
        tag = _text(release.get('tag_name'))
        asset = _midnight_asset(release)
        existing = await stored_versions()
        read = published = 0
        with tempfile.TemporaryDirectory(prefix='imbi-cve-') as tmp:
            outer = pathlib.Path(tmp) / 'outer.zip'
            inner = pathlib.Path(tmp) / 'cves.zip'
            await _download(client, asset, outer)
            await asyncio.to_thread(_extract_inner, outer, inner)
            outer.unlink()
            batches = changed_batches(inner, existing)
            while item := await asyncio.to_thread(next, batches, None):
                batch, read = item
                if batch:
                    await iggy.publish(
                        STREAM,
                        TOPIC,
                        typing.cast('list[pydantic.BaseModel]', batch),
                    )
                    published += len(batch)
    LOGGER.info(
        'CVE import %s: read %d records, published %d', tag, read, published
    )
    return ImportResult(release=tag, records=read, published=published)


# ----- Lookup ----------------------------------------------------------


_LOOKUP_SQL: typing.LiteralString = (
    'SELECT cve_id, state, assigner, published_at, updated_at, title,'
    ' description, cvss_score, cvss_severity, cvss_vector, cwe_ids,'
    ' references FROM imbi.cves FINAL'
    ' WHERE cve_id IN (SELECT id FROM cve_ids)'
)


async def lookup(cve_ids: abc.Collection[str]) -> dict[str, CveRecord]:
    """Read the catalog rows of ``cve_ids`` in one query, by CVE ID.

    An ID that is not in the catalog is not in the result.
    """
    if not cve_ids:
        return {}
    rows = await clickhouse.query(
        _LOOKUP_SQL, tables={'cve_ids': sorted(cve_ids)}
    )
    out: dict[str, CveRecord] = {}
    for row in rows:
        row['published_at'] = clickhouse.as_utc_or_none(row['published_at'])
        row['updated_at'] = clickhouse.as_utc(row['updated_at'])
        record = CveRecord.model_validate(row)
        out[record.cve_id] = record
    return out
