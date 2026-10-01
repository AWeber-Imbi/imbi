"""Tests for the pointer, normalize, template, diff, and timing code."""

import unittest

from scripts.replay import (
    diff,
    models,
    normalize,
    pointer,
    templates,
    timings,
)


def exchange(**values: object) -> models.Exchange:
    base: dict[str, object] = {
        'key': 'GET /api/things/1',
        'kind': 'get',
        'route': 'GET /api/things/{id}',
        'method': 'GET',
        'path': '/api/things/1',
        'status': 200,
        'body': None,
        'elapsed_ms': [1.0],
    }
    base.update(values)
    return models.Exchange.model_validate(base)


class PointerTestCase(unittest.TestCase):
    def test_single_segment_wildcard(self) -> None:
        self.assertTrue(pointer.matches('/data/*/id', ('data', '0', 'id')))
        self.assertFalse(pointer.matches('/data/*/id', ('data', 'id')))

    def test_any_depth_wildcard(self) -> None:
        self.assertTrue(pointer.matches('/**/id', ('id',)))
        self.assertTrue(pointer.matches('/**/id', ('a', 'b', 'id')))
        self.assertFalse(pointer.matches('/**/id', ('a', 'ids')))

    def test_root(self) -> None:
        self.assertTrue(pointer.matches('', ()))
        self.assertFalse(pointer.matches('', ('a',)))

    def test_escape_round_trip(self) -> None:
        path = ('a/b', 'c~d')
        self.assertEqual(pointer.to_pointer(path), '/a~1b/c~0d')
        self.assertEqual(pointer.parse('/a~1b/c~0d'), path)

    def test_pattern_needs_slash(self) -> None:
        with self.assertRaises(ValueError):
            pointer.parse('id')


class NormalizeTestCase(unittest.TestCase):
    def test_masks_only_listed_fields(self) -> None:
        value = {'id': 'x', 'name': 'n', 'items': [{'id': 1}, {'id': 2}]}
        result = normalize.apply(value, ['/id', '/items/*/id'])
        self.assertEqual(
            result,
            {
                'id': '<normalized:str>',
                'name': 'n',
                'items': [
                    {'id': '<normalized:int>'},
                    {'id': '<normalized:int>'},
                ],
            },
        )

    def test_mask_keeps_the_type(self) -> None:
        value: dict[str, object] = {'a': True, 'b': 1.5, 'c': {}, 'd': []}
        result = normalize.apply(value, ['/a', '/b', '/c', '/d'])
        self.assertEqual(
            result,
            {
                'a': '<normalized:bool>',
                'b': '<normalized:float>',
                'c': '<normalized:object>',
                'd': '<normalized:array>',
            },
        )
        report = differ(
            rules=[models.NormalizeRule(pointer='/n', reason='r')]
        ).run([exchange(body={'n': '1'})], [exchange(body={'n': 1})])
        self.assertEqual(len(report.unexpected), 1)

    def test_keeps_null_and_missing(self) -> None:
        value = {'id': None}
        self.assertEqual(normalize.apply(value, ['/id', '/other']), value)

    def test_keeps_list_order(self) -> None:
        self.assertEqual(normalize.apply([3, 1, 2], ['/x']), [3, 1, 2])

    def test_rules_select_by_route_or_key(self) -> None:
        rules = [
            models.NormalizeRule(
                route='GET /api/things/*', pointer='/a', reason='r'
            ),
            models.NormalizeRule(route='scenario:*', pointer='/b', reason='r'),
        ]
        item = exchange(normalize=['/c'])
        self.assertEqual(normalize.pointers_for(rules, item), ['/a', '/c'])


class TemplatesTestCase(unittest.TestCase):
    def test_match_and_fill(self) -> None:
        template = '/api/o/{org_slug}/users/{email}'
        path = templates.fill(template, {'org_slug': 'a', 'email': 'x@y/z'})
        self.assertEqual(path, '/api/o/a/users/x%40y%2Fz')
        self.assertEqual(
            templates.match(template, path),
            {'org_slug': 'a', 'email': 'x@y/z'},
        )

    def test_fill_needs_every_value(self) -> None:
        with self.assertRaises(KeyError):
            templates.fill('/a/{b}', {})

    def test_literal_segment_wins(self) -> None:
        table = templates.RouteTable(
            (
                'GET /api/p/{project_id}/releases/{release_id}',
                'GET /api/p/{project_id}/releases/current',
                'POST /api/p/{project_id}/releases/current',
            )
        )
        self.assertEqual(
            table.resolve('GET', '/api/p/1/releases/current'),
            'GET /api/p/{project_id}/releases/current',
        )
        self.assertEqual(
            table.resolve('GET', '/api/p/1/releases/r1'),
            'GET /api/p/{project_id}/releases/{release_id}',
        )
        self.assertIsNone(table.resolve('DELETE', '/api/p/1/releases/r1'))

    def test_move_prefix(self) -> None:
        moves = [
            models.Move(
                old='/api/roles',
                new='/api/organizations/{org_slug}/roles',
                owner='M',
            )
        ]
        variables = {'org_slug': 'acme'}
        self.assertEqual(
            templates.move(moves, 'GET', '/api/roles/admin', variables),
            '/api/organizations/acme/roles/admin',
        )
        self.assertEqual(
            templates.move(moves, 'GET', '/api/rolesx', variables),
            '/api/rolesx',
        )

    def test_move_with_parameter_method_and_exact(self) -> None:
        moves = [
            models.Move(
                old='/api/admin/plugins/{slug}/entities',
                new='/api/organizations/{org_slug}/plugins/{slug}/entities',
                owner='T',
            ),
            models.Move(
                old='/api/uploads/',
                new='/api/organizations/{org_slug}/uploads/',
                methods=['POST'],
                exact=True,
                owner='Q',
            ),
        ]
        variables = {'org_slug': 'acme'}
        self.assertEqual(
            templates.move(
                moves, 'GET', '/api/admin/plugins/aws/entities/A/1', variables
            ),
            '/api/organizations/acme/plugins/aws/entities/A/1',
        )
        self.assertEqual(
            templates.move(moves, 'POST', '/api/uploads/', variables),
            '/api/organizations/acme/uploads/',
        )
        self.assertEqual(
            templates.move(moves, 'GET', '/api/uploads/', variables),
            '/api/uploads/',
        )
        self.assertEqual(
            templates.move(moves, 'POST', '/api/uploads/x', variables),
            '/api/uploads/x',
        )


def differ(
    expected: list[models.ExpectedConfig] | None = None,
    rules: list[models.NormalizeRule] | None = None,
) -> diff.Differ:
    return diff.Differ(
        rules=rules or [],
        expected=expected or [],
        owners=models.OwnersConfig(routes={'GET /api/things/{id}': 'K'}),
    )


class CompareValuesTestCase(unittest.TestCase):
    def test_null_and_missing_are_different(self) -> None:
        found = list(diff.compare_values({'a': None}, {}))
        self.assertEqual(found, [(('a',), None, pointer.MISSING)])

    def test_list_order_matters(self) -> None:
        found = list(diff.compare_values([1, 2], [2, 1]))
        self.assertEqual(found, [(('0',), 1, 2), (('1',), 2, 1)])

    def test_extra_list_item(self) -> None:
        found = list(diff.compare_values([1], [1, 2]))
        self.assertEqual(found, [(('1',), pointer.MISSING, 2)])

    def test_types_are_compared(self) -> None:
        self.assertEqual(len(list(diff.compare_values(1, True))), 1)
        self.assertEqual(len(list(diff.compare_values(1, 1.0))), 1)
        self.assertEqual(list(diff.compare_values({'a': 1}, {'a': 1})), [])


class DifferTestCase(unittest.TestCase):
    def test_equal_recordings(self) -> None:
        old = [exchange(body={'a': 1})]
        report = differ().run(old, [exchange(body={'a': 1})])
        self.assertEqual(report.compared, 1)
        self.assertEqual(report.differences, [])

    def test_status_and_body_differences_group_by_owner(self) -> None:
        report = differ().run(
            [exchange(body={'a': 1})],
            [exchange(status=404, body={'detail': 'x'})],
        )
        fields = [(item.field, item.pointer) for item in report.unexpected]
        self.assertEqual(
            fields,
            [('status', ''), ('body', '/a'), ('body', '/detail')],
        )
        self.assertEqual(list(report.by_owner()), ['K'])

    def test_missing_exchange(self) -> None:
        report = differ().run([exchange()], [])
        self.assertEqual(report.unexpected[0].field, 'exchange')
        self.assertEqual(report.unexpected[0].new, pointer.MISSING)

    def test_unknown_route_goes_to_default_owner(self) -> None:
        item = exchange(route='GET /api/other')
        report = differ().run(
            [item], [exchange(route='GET /api/other', status=500)]
        )
        self.assertEqual(list(report.by_owner()), ['orchestrator'])

    def test_normalize_rule_hides_difference(self) -> None:
        rules = [models.NormalizeRule(route='*', pointer='/at', reason='time')]
        report = differ(rules=rules).run(
            [exchange(body={'at': '1'})], [exchange(body={'at': '2'})]
        )
        self.assertEqual(report.differences, [])

    def test_unstable_fields_are_reported_not_masked(self) -> None:
        report = differ().run(
            [exchange(body={'at': '1'}, unstable=['/at'])],
            [exchange(body={'at': '2'})],
        )
        self.assertEqual(len(report.differences), 1)
        self.assertEqual(report.unstable, {'GET /api/things/{id}': ['/at']})
        self.assertIn('/at', diff.format_text(report, values=False))

    def test_unstable_fields_with_a_rule(self) -> None:
        rules = [models.NormalizeRule(pointer='/**/at', reason='time')]
        report = differ(rules=rules).run(
            [exchange(body={'at': '1'}, unstable=['/at'])],
            [exchange(body={'at': '2'})],
        )
        self.assertEqual(report.differences, [])
        self.assertEqual(report.unstable, {})

    def test_unstable_on_the_new_side_fails(self) -> None:
        report = differ().run(
            [exchange(body={'items': [1, 2]})],
            [exchange(body={'items': [1, 2]}, unstable=['/items/0'])],
        )
        self.assertEqual(report.unexpected, [])
        self.assertEqual(
            report.unstable_new, {'GET /api/things/{id}': ['/items/*']}
        )
        self.assertTrue(report.failed)
        self.assertIn('new side', diff.format_text(report, values=False))

    def test_mask_unstable_masks_the_old_side_only(self) -> None:
        masking = diff.Differ(
            rules=[],
            expected=[],
            owners=models.OwnersConfig(),
            mask_unstable=True,
        )
        report = masking.run(
            [exchange(body={'at': '1'})],
            [exchange(body={'at': '2'}, unstable=['/at'])],
        )
        self.assertEqual(len(report.unexpected), 1)
        self.assertTrue(report.failed)

    def test_mask_unstable(self) -> None:
        masking = diff.Differ(
            rules=[],
            expected=[],
            owners=models.OwnersConfig(),
            mask_unstable=True,
        )
        report = masking.run(
            [exchange(body={'at': '1'}, unstable=['/at'])],
            [exchange(body={'at': '2'})],
        )
        self.assertEqual(report.differences, [])

    def test_expected_difference(self) -> None:
        expected = models.ExpectedConfig(
            domain='things',
            owner='K',
            difference=[
                models.ExpectedDifference(
                    route='GET /api/things/*',
                    field='body',
                    pointer='/icon',
                    new='<missing>',
                    reason='not carried over',
                ),
                models.ExpectedDifference(
                    route='GET /api/things/*',
                    field='status',
                    old=204,
                    new=409,
                    reason='never happens',
                ),
            ],
        )
        report = differ([expected]).run(
            [exchange(body={'icon': None, 'name': 'a'})],
            [exchange(body={'name': 'b'})],
        )
        self.assertEqual(len(report.expected), 1)
        self.assertEqual(report.expected[0].pointer, '/icon')
        self.assertEqual(
            [item.pointer for item in report.unexpected], ['/name']
        )
        self.assertEqual(len(report.unused_expectations), 1)

    def test_expected_value_must_match(self) -> None:
        expected = models.ExpectedConfig(
            domain='things',
            owner='K',
            difference=[
                models.ExpectedDifference(
                    route='GET /api/things/*',
                    field='status',
                    old=204,
                    new=409,
                    reason='restrict',
                )
            ],
        )
        report = differ([expected]).run(
            [exchange(status=204)], [exchange(status=500)]
        )
        self.assertEqual(len(report.unexpected), 1)

    def test_expected_body_limited_to_a_status_change(self) -> None:
        expected = models.ExpectedConfig(
            domain='things',
            owner='K',
            difference=[
                models.ExpectedDifference(
                    route='GET /api/things/*',
                    field='body',
                    old_status=404,
                    new_status=200,
                    reason='restrict',
                )
            ],
        )
        same_status = differ([expected]).run(
            [exchange(status=404, body={'a': 1})],
            [exchange(status=404, body={'a': 2})],
        )
        self.assertEqual(len(same_status.unexpected), 1)
        changed = differ([expected]).run(
            [exchange(status=404, body={'a': 1})],
            [exchange(status=200, body={'a': 2})],
        )
        self.assertEqual(
            [item.field for item in changed.unexpected], ['status']
        )
        self.assertEqual(len(changed.expected), 1)

    def test_format_text(self) -> None:
        report = differ().run(
            [exchange(body={'a': 'secret'})], [exchange(body={'a': 'b'})]
        )
        with_values = diff.format_text(report, values=True)
        without = diff.format_text(report, values=False)
        self.assertIn('## owner K: 1', with_values)
        self.assertIn('"secret"', with_values)
        self.assertNotIn('secret', without)
        self.assertNotIn('/api/things/1 ', without)
        self.assertIn('GET /api/things/{id} #', without)

    def test_format_text_limits_body_differences(self) -> None:
        count = diff.MAX_BODY_DIFFERENCES + 5
        report = differ().run(
            [exchange(body=list(range(count)))],
            [exchange(body=[-1] * count)],
        )
        text = diff.format_text(report, values=False)
        self.assertIn('(5 more body differences not shown)', text)


class TimingsTestCase(unittest.TestCase):
    def test_percentile(self) -> None:
        samples = [float(value) for value in range(1, 101)]
        self.assertEqual(timings.percentile(samples, 50), 50.0)
        self.assertEqual(timings.percentile(samples, 95), 95.0)
        self.assertEqual(timings.percentile([7.0], 95), 7.0)
        with self.assertRaises(ValueError):
            timings.percentile([], 50)

    def test_compare_and_format(self) -> None:
        old = [exchange(elapsed_ms=[10.0, 10.0])]
        new = [exchange(elapsed_ms=[20.0, 20.0]), exchange(status=0)]
        rows = timings.compare(old, new)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ratio, 2.0)
        table = timings.format_markdown(rows, 1.2)
        self.assertIn('| 2.00 | slower |', table)
