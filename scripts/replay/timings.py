"""p50 and p95 per route, for the old and the new recording."""

import collections
import dataclasses
import math
import typing

if typing.TYPE_CHECKING:
    from scripts.replay import models


def percentile(samples: list[float], rank: float) -> float:
    """Return the nearest-rank percentile of ``samples``."""
    if not samples:
        raise ValueError('no samples')
    ordered = sorted(samples)
    index = max(math.ceil(rank / 100 * len(ordered)) - 1, 0)
    return ordered[index]


@dataclasses.dataclass(frozen=True)
class Row:
    route: str
    old_count: int
    old_p50: float | None
    old_p95: float | None
    new_count: int
    new_p50: float | None
    new_p95: float | None

    @property
    def ratio(self) -> float | None:
        """The new p95 divided by the old p95."""
        if not self.old_p95 or self.new_p95 is None:
            return None
        return self.new_p95 / self.old_p95


def _samples(
    exchanges: list[models.Exchange],
) -> dict[str, list[float]]:
    result: dict[str, list[float]] = collections.defaultdict(list)
    for exchange in exchanges:
        if exchange.status == 0:
            continue
        result[exchange.route].extend(exchange.elapsed_ms)
    return result


def compare(
    old: list[models.Exchange], new: list[models.Exchange]
) -> list[Row]:
    old_samples = _samples(old)
    new_samples = _samples(new)
    rows: list[Row] = []
    for route in sorted(set(old_samples) | set(new_samples)):
        before = old_samples.get(route, [])
        after = new_samples.get(route, [])
        rows.append(
            Row(
                route=route,
                old_count=len(before),
                old_p50=percentile(before, 50) if before else None,
                old_p95=percentile(before, 95) if before else None,
                new_count=len(after),
                new_p50=percentile(after, 50) if after else None,
                new_p95=percentile(after, 95) if after else None,
            )
        )
    return rows


def _ms(value: float | None) -> str:
    return '' if value is None else f'{value:.1f}'


def format_markdown(rows: list[Row], threshold: float) -> str:
    """Return a Markdown table. ``slower`` marks a p95 ratio over the
    threshold."""
    lines = [
        '| Route | n old | p50 old | p95 old | n new | p50 new | p95 new '
        '| p95 new/old | |',
        '|---|---|---|---|---|---|---|---|---|',
    ]
    for row in rows:
        ratio = row.ratio
        flag = 'slower' if ratio is not None and ratio > threshold else ''
        lines.append(
            f'| `{row.route}` | {row.old_count} | {_ms(row.old_p50)} '
            f'| {_ms(row.old_p95)} | {row.new_count} | {_ms(row.new_p50)} '
            f'| {_ms(row.new_p95)} '
            f'| {"" if ratio is None else f"{ratio:.2f}"} | {flag} |'
        )
    return '\n'.join(lines) + '\n'
