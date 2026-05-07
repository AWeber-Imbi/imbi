"""Tests for the log_group_names pattern parser."""

import unittest

from imbi_common.plugins.base import PluginContext

from imbi_plugin_aws.log_groups import (
    Entry,
    compile_matcher,
    literal_prefix,
    parse_entries,
)


def _ctx(slug: str = 'widget') -> PluginContext:
    return PluginContext(
        project_id='proj-1',
        project_slug=slug,
        org_slug='acme',
        environment='prod',
    )


class ParseEntriesTestCase(unittest.TestCase):
    def test_literal_no_metachars(self) -> None:
        entries = parse_entries('/aws/lambda/widget-prod', _ctx())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, 'literal')
        self.assertEqual(entries[0].expanded, '/aws/lambda/widget-prod')

    def test_template_substitution(self) -> None:
        entries = parse_entries('/imbi/${environment}/${project_slug}', _ctx())
        self.assertEqual(entries[0].kind, 'literal')
        self.assertEqual(entries[0].expanded, '/imbi/prod/widget')

    def test_glob_classified(self) -> None:
        entries = parse_entries(
            '/aws/rds/${project_slug}-*/postgresql', _ctx()
        )
        self.assertEqual(entries[0].kind, 'glob')
        self.assertEqual(entries[0].expanded, '/aws/rds/widget-*/postgresql')

    def test_regex_classified(self) -> None:
        entries = parse_entries(
            r'regex:/aws/rds/${project_slug}-\d+/postgresql', _ctx()
        )
        self.assertEqual(entries[0].kind, 'regex')
        self.assertEqual(
            entries[0].expanded, r'/aws/rds/widget-\d+/postgresql'
        )

    def test_regex_escapes_template_vars(self) -> None:
        # A slug with a '.' must not turn into a regex metachar after
        # template expansion.
        entries = parse_entries(
            r'regex:/aws/rds/${project_slug}-\d+', _ctx(slug='my.app')
        )
        self.assertEqual(entries[0].kind, 'regex')
        self.assertEqual(entries[0].expanded, r'/aws/rds/my\.app-\d+')

    def test_prefix_classified(self) -> None:
        entries = parse_entries('prefix:/aws/lambda/${project_slug}-', _ctx())
        self.assertEqual(entries[0].kind, 'prefix')
        self.assertEqual(entries[0].expanded, '/aws/lambda/widget-')

    def test_prefix_rejects_wildcards(self) -> None:
        with self.assertRaisesRegex(ValueError, 'wildcards'):
            parse_entries('prefix:/aws/lambda/widget-*', _ctx())

    def test_regex_rejects_invalid_pattern(self) -> None:
        with self.assertRaisesRegex(ValueError, 'invalid regex'):
            parse_entries('regex:[invalid', _ctx())

    def test_regex_marker_without_body_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, 'requires'):
            parse_entries('regex:', _ctx())

    def test_prefix_marker_without_body_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, 'requires'):
            parse_entries('prefix:', _ctx())

    def test_empty_after_split_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_entries(' , , ', _ctx())

    def test_mixed_kinds_returned_in_order(self) -> None:
        entries = parse_entries(
            '/literal/one, /glob/${project_slug}-*, '
            r'regex:/r/\d+, prefix:/p/',
            _ctx(),
        )
        kinds = [e.kind for e in entries]
        self.assertEqual(kinds, ['literal', 'glob', 'regex', 'prefix'])


class LiteralPrefixTestCase(unittest.TestCase):
    def test_glob_stops_at_first_metachar(self) -> None:
        self.assertEqual(
            literal_prefix('/aws/rds/widget-*/postgresql', is_regex=False),
            '/aws/rds/widget-',
        )

    def test_glob_returns_full_pattern_when_no_metachar(self) -> None:
        self.assertEqual(
            literal_prefix('/aws/lambda/widget-prod', is_regex=False),
            '/aws/lambda/widget-prod',
        )

    def test_regex_stops_at_backslash(self) -> None:
        self.assertEqual(
            literal_prefix(r'/aws/rds/widget-\d+/postgresql', is_regex=True),
            '/aws/rds/widget-',
        )

    def test_regex_stops_at_dot(self) -> None:
        self.assertEqual(
            literal_prefix('/aws/rds/widget.+', is_regex=True),
            '/aws/rds/widget',
        )

    def test_metachar_at_start_returns_empty(self) -> None:
        self.assertEqual(literal_prefix('*foo', is_regex=False), '')


class CompileMatcherTestCase(unittest.TestCase):
    def test_glob_matches_anchored(self) -> None:
        m = compile_matcher('/aws/rds/widget-*/postgresql', is_regex=False)
        self.assertTrue(m.match('/aws/rds/widget-1/postgresql'))
        self.assertTrue(m.match('/aws/rds/widget-prod/postgresql'))
        self.assertFalse(m.match('/aws/rds/other/postgresql'))

    def test_regex_matches_anchored(self) -> None:
        m = compile_matcher(r'/aws/rds/widget-\d+/postgresql', is_regex=True)
        self.assertTrue(m.match('/aws/rds/widget-7/postgresql'))
        self.assertFalse(m.match('/aws/rds/widget-prod/postgresql'))


class EntryShapeTestCase(unittest.TestCase):
    def test_entry_keeps_raw(self) -> None:
        entries = parse_entries('regex:/foo/.*', _ctx())
        self.assertIsInstance(entries[0], Entry)
        self.assertEqual(entries[0].raw, 'regex:/foo/.*')
