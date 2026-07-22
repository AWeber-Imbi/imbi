"""Tests for EXISTS_IN surfacing on :class:`ProjectResponse`.

Exercises the ``_build_services`` model validator that turns the read
fragment's ``service_edges`` (+ the dashboard URL from ``links``) into
the read-only ``services`` list, leaving ``identifiers`` untouched.
"""

import unittest

from imbi.api.endpoints.projects import ProjectResponse


class BuildServicesTestCase(unittest.TestCase):
    def _build(self, data: dict[str, object]) -> dict[str, object]:
        return ProjectResponse._build_services(data)

    def test_no_edges_is_passthrough(self) -> None:
        data = {'identifiers': {'a': 1}}
        self.assertEqual(self._build(dict(data)), data)

    def test_builds_services_with_dashboard_from_links(self) -> None:
        out = self._build(
            {
                'identifiers': {},
                'links': {'github': 'https://aweber.ghe.com/o/r'},
                'service_edges': [
                    {
                        'slug': 'github',
                        'name': 'GitHub',
                        'identifier': 134741,
                        'canonical_url': (
                            'https://api.aweber.ghe.com/repositories/134741'
                        ),
                    }
                ],
            }
        )
        services = out['services']
        assert isinstance(services, list)
        self.assertEqual(len(services), 1)
        svc = services[0]
        self.assertEqual(svc['integration_slug'], 'github')
        self.assertEqual(svc['integration_name'], 'GitHub')
        # numeric identifier is stringified
        self.assertEqual(svc['identifier'], '134741')
        self.assertEqual(
            svc['canonical_url'],
            'https://api.aweber.ghe.com/repositories/134741',
        )
        self.assertEqual(svc['dashboard_url'], 'https://aweber.ghe.com/o/r')
        # service_edges is consumed
        self.assertNotIn('service_edges', out)

    def test_identifiers_are_not_touched(self) -> None:
        # The edge identifier must NOT be merged into identifiers — the
        # node map is the editable source of truth.
        out = self._build(
            {
                'identifiers': {'github': '999'},
                'links': {},
                'service_edges': [
                    {'slug': 'github', 'name': 'GitHub', 'identifier': 134741}
                ],
            }
        )
        self.assertEqual(out['identifiers'], {'github': '999'})
        self.assertEqual(out['services'][0]['identifier'], '134741')  # type: ignore[index]

    def test_links_json_string_is_parsed(self) -> None:
        out = self._build(
            {
                'links': '{"github": "https://dash/x"}',
                'service_edges': [
                    {'slug': 'github', 'name': 'GitHub', 'identifier': '1'}
                ],
            }
        )
        self.assertEqual(out['services'][0]['dashboard_url'], 'https://dash/x')  # type: ignore[index]

    def test_missing_dashboard_is_none(self) -> None:
        out = self._build(
            {
                'links': {},
                'service_edges': [
                    {
                        'slug': 'sonarqube',
                        'name': 'SonarQube',
                        'identifier': 'cc:webform',
                        'canonical_url': None,
                    }
                ],
            }
        )
        svc = out['services'][0]  # type: ignore[index]
        self.assertIsNone(svc['dashboard_url'])
        self.assertIsNone(svc['canonical_url'])


if __name__ == '__main__':
    unittest.main()
