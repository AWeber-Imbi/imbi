import unittest

from imbi.common.plugins.templates import expand_template, validate_template


class ValidateTemplateTestCase(unittest.TestCase):
    def test_validate_template_valid(self) -> None:
        validate_template('${project_slug}/logs/${environment}')

    def test_validate_template_unknown_var(self) -> None:
        with self.assertRaises(ValueError):
            validate_template('${unknown_var}')

    def test_validate_template_all_allowed_vars(self) -> None:
        validate_template(
            '${project_slug}/${org_slug}/${team_slug}/${environment}/'
            '${project_id}/${project_type_slug}'
        )

    def test_validate_template_project_type_slug(self) -> None:
        validate_template('${project_type_slug}/${project_slug}')

    def test_validate_template_mixed_valid_invalid(self) -> None:
        with self.assertRaises(ValueError):
            validate_template('${project_slug}/${bad_var}')


class ExpandTemplateTestCase(unittest.TestCase):
    def test_expand_template(self) -> None:
        result = expand_template(
            '${project_slug}-${environment}',
            {'project_slug': 'myapp', 'environment': 'prod'},
        )
        self.assertEqual(result, 'myapp-prod')

    def test_expand_template_missing_var(self) -> None:
        result = expand_template(
            '${project_slug}-${environment}',
            {'project_slug': 'myapp'},
        )
        self.assertEqual(result, 'myapp-')

    def test_expand_template_all_vars(self) -> None:
        result = expand_template(
            '${project_slug}/${org_slug}/${environment}/${project_id}',
            {
                'project_slug': 'my-app',
                'org_slug': 'acme',
                'environment': 'staging',
                'project_id': 'abc123',
            },
        )
        self.assertEqual(result, 'my-app/acme/staging/abc123')

    def test_expand_template_none_value(self) -> None:
        result = expand_template(
            '${project_slug}',
            {'project_slug': None},
        )
        self.assertEqual(result, '')

    def test_expand_template_rejects_unknown_var(self) -> None:
        with self.assertRaises(ValueError):
            expand_template('${rogue_var}', {'rogue_var': 'evil'})

    def test_expand_template_project_type_slug(self) -> None:
        result = expand_template(
            '${project_type_slug}/${project_slug}',
            {'project_type_slug': 'api', 'project_slug': 'billing'},
        )
        self.assertEqual(result, 'api/billing')
