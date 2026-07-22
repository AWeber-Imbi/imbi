"""Tests for the CloudWatch Logs Insights query builder + cursor."""

import datetime
import unittest

from imbi_common.plugins.base import LogFilter
from imbi_common.plugins.errors import CursorExpiredError

from imbi_plugin_aws import query


class FilterClauseTestCase(unittest.TestCase):
    def test_eq_quotes_value(self) -> None:
        clause = query.filter_clause(
            LogFilter(field='level', op='eq', value='ERROR')
        )
        self.assertEqual(clause, 'filter level = "ERROR"')

    def test_ne(self) -> None:
        clause = query.filter_clause(
            LogFilter(field='level', op='ne', value='DEBUG')
        )
        self.assertEqual(clause, 'filter level != "DEBUG"')

    def test_contains_uses_like(self) -> None:
        clause = query.filter_clause(
            LogFilter(field='message', op='contains', value='timeout')
        )
        self.assertEqual(clause, 'filter @message like "timeout"')

    def test_starts_with_builds_anchored_regex(self) -> None:
        clause = query.filter_clause(
            LogFilter(field='message', op='starts_with', value='ERR')
        )
        self.assertEqual(clause, 'filter @message like /^ERR/')

    def test_regex_passthrough(self) -> None:
        clause = query.filter_clause(
            LogFilter(field='@message', op='regex', value='ERR.*')
        )
        self.assertEqual(clause, 'filter @message like /ERR.*/')


class LevelsClauseTestCase(unittest.TestCase):
    def test_levels_clause_in_build_query(self) -> None:
        q = query.build_query(
            base_filter=None,
            filters=[],
            limit=10,
            level_field='level',
            levels=['ERROR', 'WARN'],
        )
        self.assertIn(
            'filter level like /(?i)^(ERROR|WARN)$/',
            q,
        )

    def test_slash_in_level_is_escaped_for_regex_literal(self) -> None:
        q = query.build_query(
            base_filter=None,
            filters=[],
            limit=10,
            level_field='level',
            levels=['WARN/X'],
        )
        # The slash in the level alias must be escaped so it does not
        # terminate the surrounding Insights regex literal.
        self.assertIn(
            r'filter level like /(?i)^(WARN\/X)$/',
            q,
        )


class BuildQueryTestCase(unittest.TestCase):
    def test_assembly_orders_clauses(self) -> None:
        q = query.build_query(
            base_filter='@logStream like "prod"',
            filters=[
                LogFilter(field='level', op='eq', value='ERROR'),
            ],
            limit=50,
        )
        self.assertEqual(
            q,
            'fields @timestamp, @message, @logStream'
            ' | filter @logStream like "prod"'
            ' | filter level = "ERROR"'
            ' | sort @timestamp desc'
            ' | limit 50',
        )

    def test_caps_limit_at_ceiling(self) -> None:
        q = query.build_query(
            base_filter=None,
            filters=[],
            limit=99999,
        )
        self.assertIn('limit 10000', q)

    def test_floors_limit_at_one(self) -> None:
        q = query.build_query(base_filter=None, filters=[], limit=0)
        self.assertIn('limit 1', q)


class CursorTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        ts = datetime.datetime(2024, 5, 1, 12, 0, 0, tzinfo=datetime.UTC)
        fp = query.query_fingerprint(
            query_string='fields @timestamp', log_group_names=['/a']
        )
        encoded = query.encode_cursor(last_seen=ts, fingerprint=fp)
        decoded = query.decode_cursor(encoded, fingerprint=fp)
        self.assertEqual(decoded, ts)

    def test_fingerprint_mismatch_raises(self) -> None:
        ts = datetime.datetime(2024, 5, 1, 12, 0, 0, tzinfo=datetime.UTC)
        fp_a = query.query_fingerprint(
            query_string='q1', log_group_names=['/a']
        )
        fp_b = query.query_fingerprint(
            query_string='q2', log_group_names=['/a']
        )
        encoded = query.encode_cursor(last_seen=ts, fingerprint=fp_a)
        with self.assertRaises(CursorExpiredError):
            query.decode_cursor(encoded, fingerprint=fp_b)

    def test_garbage_cursor_raises(self) -> None:
        with self.assertRaises(CursorExpiredError):
            query.decode_cursor('not-base64!@#', fingerprint='x')

    def test_log_group_order_independent_fingerprint(self) -> None:
        fp_a = query.query_fingerprint(
            query_string='q', log_group_names=['/a', '/b']
        )
        fp_b = query.query_fingerprint(
            query_string='q', log_group_names=['/b', '/a']
        )
        self.assertEqual(fp_a, fp_b)
