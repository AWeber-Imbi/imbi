"""Promotion pipelines derived from the flat environment list.

Environments are one list ordered by ``sort_order``, but that list may
hold several independent pipelines: an environment whose ``terminal``
flag is true ends its pipeline, and the next environment by
``sort_order`` starts a new one (#285).  Every consumer that walks
"adjacent environments" as promotion steps must derive its pairs here,
so a step is never invented across the seam between two pipelines.
"""

from __future__ import annotations

import collections.abc
import itertools
import typing

Env: typing.TypeAlias = collections.abc.Mapping[str, typing.Any]


def sort_key(environment: Env) -> tuple[int, str]:
    """The canonical environment ordering: ``sort_order``, then name."""
    return (
        int(environment.get('sort_order') or 0),
        str(environment.get('name') or ''),
    )


def split_chains[T](
    items: collections.abc.Iterable[T],
    *,
    environment: collections.abc.Callable[[T], Env] | None = None,
) -> list[list[T]]:
    """Sort ``items`` into pipeline order and split into pipelines.

    A chain ends at (and includes) each item whose environment is
    ``terminal``; the next item starts a new chain.  ``environment``
    maps an item to its environment mapping, for callers whose items
    wrap the environment rather than being one.
    """

    def env_of(item: T) -> Env:
        if environment is not None:
            return environment(item)
        return typing.cast('Env', item)

    ordered = sorted(items, key=lambda item: sort_key(env_of(item)))
    chains: list[list[T]] = []
    chain: list[T] = []
    for item in ordered:
        chain.append(item)
        if env_of(item).get('terminal'):
            chains.append(chain)
            chain = []
    if chain:
        chains.append(chain)
    return chains


def promotion_pairs[T](
    items: collections.abc.Iterable[T],
    *,
    environment: collections.abc.Callable[[T], Env] | None = None,
) -> list[tuple[T, T]]:
    """Adjacent pairs within each pipeline, in pipeline order.

    Each pair is one promotion step ``(head, base)`` where ``head`` is
    the environment earlier in the pipeline (lower ``sort_order``).  No
    pair spans a terminal boundary.
    """
    return [
        pair
        for chain in split_chains(items, environment=environment)
        for pair in itertools.pairwise(chain)
    ]
