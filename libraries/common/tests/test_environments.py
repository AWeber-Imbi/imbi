"""Tests for promotion-pipeline derivation from environment lists."""

from __future__ import annotations

import typing
import unittest

from imbi.common import environments


def _env(
    slug: str, order: int, *, terminal: bool = False
) -> dict[str, typing.Any]:
    env: dict[str, typing.Any] = {
        'name': slug.title(),
        'slug': slug,
        'sort_order': order,
    }
    if terminal:
        env['terminal'] = True
    return env


class SortKeyTests(unittest.TestCase):
    def test_orders_by_sort_order_then_name(self) -> None:
        envs = [_env('bravo', 2), _env('alpha', 2), _env('zulu', 1)]
        ordered = sorted(envs, key=environments.sort_key)
        self.assertEqual(
            ['zulu', 'alpha', 'bravo'], [e['slug'] for e in ordered]
        )

    def test_missing_sort_order_reads_as_zero(self) -> None:
        self.assertEqual((0, 'X'), environments.sort_key({'name': 'X'}))


class SplitChainsTests(unittest.TestCase):
    def test_one_pipeline_is_one_sorted_chain(self) -> None:
        chains = environments.split_chains(
            [_env('staging', 2), _env('testing', 1)]
        )
        self.assertEqual(
            [['testing', 'staging']],
            [[e['slug'] for e in chain] for chain in chains],
        )

    def test_a_terminal_environment_ends_its_chain(self) -> None:
        chains = environments.split_chains(
            [
                _env('infra-testing', 1),
                _env('infra', 2, terminal=True),
                _env('testing', 3),
                _env('staging', 4),
            ]
        )
        self.assertEqual(
            [['infra-testing', 'infra'], ['testing', 'staging']],
            [[e['slug'] for e in chain] for chain in chains],
        )

    def test_a_terminal_final_environment_adds_no_empty_chain(self) -> None:
        chains = environments.split_chains(
            [_env('testing', 1), _env('production', 2, terminal=True)]
        )
        self.assertEqual(1, len(chains))

    def test_empty_input_has_no_chains(self) -> None:
        self.assertEqual([], environments.split_chains([]))

    def test_wrapped_items_split_via_the_environment_key(self) -> None:
        items = [
            {'env': _env('infra', 1, terminal=True), 'release': 'a'},
            {'env': _env('testing', 2), 'release': 'b'},
        ]
        chains = environments.split_chains(
            items, environment=lambda item: item['env']
        )
        self.assertEqual(
            [['a'], ['b']],
            [[item['release'] for item in chain] for chain in chains],
        )


class PromotionPairsTests(unittest.TestCase):
    def test_pairs_are_adjacent_within_one_pipeline(self) -> None:
        pairs = environments.promotion_pairs(
            [_env('testing', 1), _env('staging', 2), _env('production', 3)]
        )
        self.assertEqual(
            [('testing', 'staging'), ('staging', 'production')],
            [(head['slug'], base['slug']) for head, base in pairs],
        )

    def test_no_pair_spans_a_terminal_boundary(self) -> None:
        pairs = environments.promotion_pairs(
            [
                _env('infra-testing', 1),
                _env('infra', 2, terminal=True),
                _env('testing', 3),
                _env('staging', 4),
            ]
        )
        self.assertEqual(
            [('infra-testing', 'infra'), ('testing', 'staging')],
            [(head['slug'], base['slug']) for head, base in pairs],
        )

    def test_an_explicit_false_terminal_does_not_split(self) -> None:
        envs = [_env('testing', 1), _env('staging', 2)]
        envs[0]['terminal'] = False
        pairs = environments.promotion_pairs(envs)
        self.assertEqual(1, len(pairs))
