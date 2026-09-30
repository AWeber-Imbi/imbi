"""Compare two recordings.

For each exchange key, the diff compares the status and the body (for
an error status the body is the error body). Lists are compared item
by item, in order. A field that is missing and a field that is
``null`` are different.

Each difference that no expected-differences file names is
*unexpected*. The report groups the unexpected differences by the
agent that owns the route.
"""

import collections
import dataclasses
import fnmatch
import hashlib
import json
import typing
from collections import abc

from scripts.replay import models, normalize, pointer, templates

#: The body differences that the report shows for one exchange. The
#: count in the report is always complete.
MAX_BODY_DIFFERENCES = 20

MISSING_TEXT = '<missing>'
NULL_TEXT = '<null>'


@dataclasses.dataclass(frozen=True)
class Difference:
    key: str
    route: str
    owner: str
    field: models.Field
    pointer: str
    old: typing.Any
    new: typing.Any
    old_status: int | None = None
    new_status: int | None = None
    expected_by: str | None = None

    def display_key(self, *, values: bool) -> str:
        """Return the key, or a key with no data values.

        The key of a recorded request is its concrete path, which holds
        ids, slugs, and email addresses. Without values, the report
        shows the route and a short digest of the key instead. A
        scenario key holds only the path template, so it stays.
        """
        if values or self.key.startswith('scenario:'):
            return self.key
        digest = hashlib.sha256(self.key.encode()).hexdigest()[:12]
        return f'{self.route} #{digest}'

    def as_dict(self, *, values: bool) -> dict[str, typing.Any]:
        result: dict[str, typing.Any] = {
            'key': self.display_key(values=values),
            'route': self.route,
            'owner': self.owner,
            'field': self.field,
            'pointer': self.pointer,
        }
        if values:
            result['old'] = _render(self.old)
            result['new'] = _render(self.new)
        if self.expected_by is not None:
            result['expected_by'] = self.expected_by
        return result


@dataclasses.dataclass
class Report:
    compared: int = 0
    differences: list[Difference] = dataclasses.field(
        default_factory=list[Difference]
    )
    unused_expectations: list[str] = dataclasses.field(
        default_factory=list[str]
    )
    #: Fields that changed between two sends of one request on one
    #: side, and that no rule masks. Each one needs a rule in
    #: normalize.toml (or a fix in the API).
    unstable: dict[str, list[str]] = dataclasses.field(
        default_factory=dict[str, list[str]]
    )

    @property
    def unexpected(self) -> list[Difference]:
        return [item for item in self.differences if item.expected_by is None]

    @property
    def expected(self) -> list[Difference]:
        return [
            item for item in self.differences if item.expected_by is not None
        ]

    def by_owner(self) -> dict[str, list[Difference]]:
        groups: dict[str, list[Difference]] = collections.defaultdict(list)
        for item in self.unexpected:
            groups[item.owner].append(item)
        return dict(sorted(groups.items()))


def _render(value: typing.Any) -> typing.Any:
    if value is pointer.MISSING:
        return MISSING_TEXT
    if value is None:
        return NULL_TEXT
    return value


def compare_values(
    old: typing.Any, new: typing.Any, path: pointer.Path = ()
) -> abc.Iterator[tuple[pointer.Path, typing.Any, typing.Any]]:
    """Yield ``(path, old, new)`` for each leaf that is different."""
    same_type = type(old) is type(new)
    if isinstance(old, dict) and isinstance(new, dict):
        old_items = typing.cast('dict[str, typing.Any]', old)
        new_items = typing.cast('dict[str, typing.Any]', new)
        keys = list(old_items) + [key for key in new_items if key not in old]
        for key in keys:
            yield from compare_values(
                old_items.get(key, pointer.MISSING),
                new_items.get(key, pointer.MISSING),
                (*path, key),
            )
        return
    if isinstance(old, list) and isinstance(new, list):
        old_list = typing.cast('list[typing.Any]', old)
        new_list = typing.cast('list[typing.Any]', new)
        for index in range(max(len(old_list), len(new_list))):
            yield from compare_values(
                old_list[index] if index < len(old_list) else pointer.MISSING,
                new_list[index] if index < len(new_list) else pointer.MISSING,
                (*path, str(index)),
            )
        return
    if not same_type or old != new:
        yield path, old, new


class Differ:
    """Compare the exchanges of an old and a new recording."""

    def __init__(
        self,
        *,
        rules: list[models.NormalizeRule],
        expected: list[models.ExpectedConfig],
        owners: models.OwnersConfig,
        mask_unstable: bool = False,
    ) -> None:
        self._rules = rules
        self._mask_unstable = mask_unstable
        self._expected = [
            (config, entry)
            for config in expected
            for entry in config.difference
        ]
        self._used: set[int] = set()
        self._unstable: dict[str, set[str]] = {}
        self._owners = owners

    def run(
        self,
        old: list[models.Exchange],
        new: list[models.Exchange],
    ) -> Report:
        report = Report()
        old_by_key = {exchange.key: exchange for exchange in old}
        new_by_key = {exchange.key: exchange for exchange in new}
        keys = list(old_by_key) + [
            key for key in new_by_key if key not in old_by_key
        ]
        for key in keys:
            before = old_by_key.get(key)
            after = new_by_key.get(key)
            report.compared += 1
            report.differences.extend(self._exchange(key, before, after))
        compared = [*old, *new]
        report.unused_expectations = [
            f'{config.domain}: {entry.field} {entry.route} {entry.key} '
            f'{entry.pointer} ({entry.reason})'
            for index, (config, entry) in enumerate(self._expected)
            if index not in self._used and _applies(entry, compared)
        ]
        report.unstable = {
            route: sorted(items)
            for route, items in sorted(self._unstable.items())
        }
        return report

    def _exchange(
        self,
        key: str,
        before: models.Exchange | None,
        after: models.Exchange | None,
    ) -> list[Difference]:
        sample = before or after
        if sample is None:  # pragma: no cover - keys come from both sides
            return []
        route = sample.route
        owner = templates.owner_of(self._owners, route)
        if before is None or after is None:
            return [
                self._classify(
                    Difference(
                        key=key,
                        route=route,
                        owner=owner,
                        field='exchange',
                        pointer='',
                        old='present' if before else pointer.MISSING,
                        new='present' if after else pointer.MISSING,
                        old_status=before.status if before else None,
                        new_status=after.status if after else None,
                    )
                )
            ]
        result: list[Difference] = []
        if before.status != after.status:
            result.append(
                self._classify(
                    Difference(
                        key=key,
                        route=route,
                        owner=owner,
                        field='status',
                        pointer='',
                        old=before.status,
                        new=after.status,
                        old_status=before.status,
                        new_status=after.status,
                    )
                )
            )
        patterns = normalize.pointers_for(self._rules, before)
        patterns += [
            item
            for item in normalize.pointers_for(self._rules, after)
            if item not in patterns
        ]
        for item in (*before.unstable, *after.unstable):
            if any(
                pointer.matches(rule, pointer.parse(item)) for rule in patterns
            ):
                continue
            general = pointer.to_pointer(
                tuple(
                    '*' if segment.isdigit() else segment
                    for segment in pointer.parse(item)
                )
            )
            self._unstable.setdefault(route, set()).add(general)
        if self._mask_unstable:
            patterns += [*before.unstable, *after.unstable]
        old_body = normalize.apply(before.body, patterns)
        new_body = normalize.apply(after.body, patterns)
        for path, old_value, new_value in compare_values(old_body, new_body):
            result.append(
                self._classify(
                    Difference(
                        key=key,
                        route=route,
                        owner=owner,
                        field='body',
                        pointer=pointer.to_pointer(path),
                        old=old_value,
                        new=new_value,
                        old_status=before.status,
                        new_status=after.status,
                    )
                )
            )
        return result

    def _classify(self, difference: Difference) -> Difference:
        for index, (config, entry) in enumerate(self._expected):
            if _expects(entry, difference):
                self._used.add(index)
                return dataclasses.replace(
                    difference,
                    expected_by=f'{config.domain}: {entry.reason}',
                )
        return difference


def _applies(
    entry: models.ExpectedDifference, exchanges: list[models.Exchange]
) -> bool:
    """Return ``True`` when an exchange of the run fits ``entry``."""
    return any(
        fnmatch.fnmatchcase(exchange.key, entry.key)
        and fnmatch.fnmatchcase(exchange.route, entry.route)
        for exchange in exchanges
    )


def _optional_equal(wanted: typing.Any, actual: typing.Any) -> bool:
    """An unset (``None``) expectation fits every value."""
    return wanted is None or wanted == actual


def _expects(entry: models.ExpectedDifference, difference: Difference) -> bool:
    body_fits = difference.field != 'body' or pointer.matches(
        entry.pointer, pointer.parse(difference.pointer)
    )
    return (
        entry.field == difference.field
        and fnmatch.fnmatchcase(difference.route, entry.route)
        and fnmatch.fnmatchcase(difference.key, entry.key)
        and body_fits
        and _optional_equal(entry.old_status, difference.old_status)
        and _optional_equal(entry.new_status, difference.new_status)
        and _optional_equal(entry.old, _render(difference.old))
        and _optional_equal(entry.new, _render(difference.new))
    )


def format_text(report: Report, *, values: bool) -> str:
    """Return the report as text, grouped by owner."""
    lines = [
        f'compared {report.compared} exchanges: '
        f'{len(report.unexpected)} unexpected differences, '
        f'{len(report.expected)} expected differences'
    ]
    for owner, items in report.by_owner().items():
        lines.append('')
        lines.append(f'## owner {owner}: {len(items)}')
        shown: collections.Counter[str] = collections.Counter()
        for item in items:
            shown[item.key] += 1
            if item.field == 'body' and shown[item.key] > MAX_BODY_DIFFERENCES:
                continue
            text = f'- {item.display_key(values=values)} [{item.field}]'
            if item.pointer:
                text += f' {item.pointer}'
            if values:
                text += (
                    f': {_short(_render(item.old))} -> '
                    f'{_short(_render(item.new))}'
                )
            lines.append(text)
        hidden = sum(
            count - MAX_BODY_DIFFERENCES
            for count in shown.values()
            if count > MAX_BODY_DIFFERENCES
        )
        if hidden:
            lines.append(f'- ({hidden} more body differences not shown)')
    if report.unstable:
        lines.append('')
        lines.append('## fields that change between two sends, with no rule')
        for route, items in report.unstable.items():
            lines.append(f'- {route}: {", ".join(items)}')
    if report.unused_expectations:
        lines.append('')
        lines.append('## expected differences that did not occur')
        lines.extend(f'- {item}' for item in report.unused_expectations)
    return '\n'.join(lines) + '\n'


def _short(value: typing.Any, limit: int = 120) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    if len(text) > limit:
        return text[: limit - 3] + '...'
    return text
