"""Tests for owner/repo resolution in :mod:`imbi_plugin_github._repos`.

Focuses on the ``preferred_key`` (third-party-service-slug) precedence
added so the dashboard link keyed by the service slug is read first,
with a transition fallback to the legacy ``github-repository`` key.
"""

import unittest

from imbi_plugin_github._repos import derive_owner_repo_from_links


class DeriveOwnerRepoTestCase(unittest.TestCase):
    def test_prefers_preferred_key_over_legacy(self) -> None:
        links = {
            'github-repository': 'https://github.com/octo/legacy',
            'github': 'https://github.com/octo/current',
        }
        self.assertEqual(
            derive_owner_repo_from_links(
                links, 'github.com', preferred_key='github'
            ),
            ('octo', 'current'),
        )

    def test_falls_back_to_legacy_when_preferred_absent(self) -> None:
        links = {'github-repository': 'https://github.com/octo/legacy'}
        self.assertEqual(
            derive_owner_repo_from_links(
                links, 'github.com', preferred_key='github'
            ),
            ('octo', 'legacy'),
        )

    def test_legacy_only_without_preferred_key(self) -> None:
        links = {'github-repository': 'https://github.com/octo/legacy'}
        self.assertEqual(
            derive_owner_repo_from_links(links, 'github.com'),
            ('octo', 'legacy'),
        )

    def test_scans_other_links_as_last_resort(self) -> None:
        links = {'docs': 'https://github.com/octo/scanned'}
        self.assertEqual(
            derive_owner_repo_from_links(
                links, 'github.com', preferred_key='github'
            ),
            ('octo', 'scanned'),
        )

    def test_skips_preferred_on_wrong_host(self) -> None:
        # preferred key points at a different host -> fall through
        links = {
            'github': 'https://example.com/not/a-repo',
            'github-repository': 'https://github.com/octo/legacy',
        }
        self.assertEqual(
            derive_owner_repo_from_links(
                links, 'github.com', preferred_key='github'
            ),
            ('octo', 'legacy'),
        )

    def test_none_when_nothing_matches(self) -> None:
        self.assertIsNone(
            derive_owner_repo_from_links(
                {}, 'github.com', preferred_key='github'
            )
        )


if __name__ == '__main__':
    unittest.main()
