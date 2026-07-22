"""Tests for Cypher property-template helpers."""

import unittest

from imbi_api.graph_sql import escape_prop, props_template, set_clause


class EscapePropTestCase(unittest.TestCase):
    def test_plain_name(self) -> None:
        self.assertEqual(escape_prop('name'), '`name`')

    def test_backtick_in_name(self) -> None:
        self.assertEqual(escape_prop('a`b'), '`a``b`')


class PropsTemplateTestCase(unittest.TestCase):
    def test_empty_dict_returns_empty_string(self) -> None:
        self.assertEqual(props_template({}), '')

    def test_single_prop(self) -> None:
        result = props_template({'slug': 'x'})
        self.assertEqual(result, '{{`slug`: {slug}}}')

    def test_multiple_props(self) -> None:
        result = props_template({'a': 1, 'b': 2})
        self.assertIn('`a`: {a}', result)
        self.assertIn('`b`: {b}', result)


class SetClauseTestCase(unittest.TestCase):
    def test_empty_dict_returns_empty_string(self) -> None:
        self.assertEqual(set_clause('n', {}), '')

    def test_single_prop(self) -> None:
        result = set_clause('n', {'name': 'x'})
        self.assertEqual(result, 'SET n.`name` = {name}')

    def test_multiple_props(self) -> None:
        result = set_clause('n', {'a': 1, 'b': 2})
        self.assertTrue(result.startswith('SET '))
        self.assertIn('n.`a` = {a}', result)
        self.assertIn('n.`b` = {b}', result)


class IdentifierValidationTestCase(unittest.TestCase):
    """Both helpers must reject keys that aren't bare identifiers."""

    def test_set_clause_rejects_dotted_key(self) -> None:
        with self.assertRaises(ValueError):
            set_clause('n', {'a.b': 1})

    def test_set_clause_rejects_brace_key(self) -> None:
        with self.assertRaises(ValueError):
            set_clause('n', {'a}; DROP': 1})

    def test_set_clause_rejects_dash(self) -> None:
        with self.assertRaises(ValueError):
            set_clause('n', {'a-b': 1})

    def test_props_template_rejects_dotted_key(self) -> None:
        with self.assertRaises(ValueError):
            props_template({'a.b': 1})

    def test_props_template_rejects_leading_digit(self) -> None:
        with self.assertRaises(ValueError):
            props_template({'1foo': 1})


if __name__ == '__main__':
    unittest.main()
