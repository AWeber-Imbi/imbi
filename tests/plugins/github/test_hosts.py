"""Tests for the shared host normalization helpers."""

import unittest

from imbi.plugins.github._hosts import (
    flavor_host,
    normalize_host,
    require_ghec_tenant_host,
)


class NormalizeHostTestCase(unittest.TestCase):
    def test_strips_scheme(self) -> None:
        self.assertEqual(
            normalize_host('https://github.example.com', 'plugin'),
            'github.example.com',
        )

    def test_accepts_bare_hostname(self) -> None:
        self.assertEqual(
            normalize_host('github.example.com', 'plugin'),
            'github.example.com',
        )

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            normalize_host('', 'plugin')

    def test_rejects_path(self) -> None:
        with self.assertRaises(ValueError):
            normalize_host('https://github.example.com/foo', 'plugin')

    def test_rejects_explicit_port(self) -> None:
        # Ports are silently dropped by ``parsed.hostname``; we'd
        # compose API URLs that point at the wrong destination.  Surface
        # the misconfiguration instead.
        with self.assertRaises(ValueError):
            normalize_host('https://github.example.com:8443', 'plugin')

    def test_rejects_bare_port(self) -> None:
        with self.assertRaises(ValueError):
            normalize_host('github.example.com:8443', 'plugin')


class RequireGhecTenantHostTestCase(unittest.TestCase):
    def test_accepts_tenant(self) -> None:
        self.assertEqual(
            require_ghec_tenant_host('tenant.ghe.com', 'plugin'),
            'tenant.ghe.com',
        )

    def test_rejects_non_ghec(self) -> None:
        with self.assertRaises(ValueError):
            require_ghec_tenant_host('github.example.com', 'plugin')

    def test_rejects_api_subdomain(self) -> None:
        with self.assertRaises(ValueError):
            require_ghec_tenant_host('api.tenant.ghe.com', 'plugin')


class FlavorHostTestCase(unittest.TestCase):
    def test_github_ignores_host(self) -> None:
        self.assertEqual(flavor_host({'flavor': 'github'}, 'p'), 'github.com')

    def test_ghec_bare_tenant_computes_full_host(self) -> None:
        self.assertEqual(
            flavor_host({'flavor': 'ghec', 'host': 'aweber'}, 'p'),
            'aweber.ghe.com',
        )

    def test_ghec_full_tenant_host_unchanged(self) -> None:
        self.assertEqual(
            flavor_host({'flavor': 'ghec', 'host': 'aweber.ghe.com'}, 'p'),
            'aweber.ghe.com',
        )

    def test_ghec_rejects_non_ghec_host(self) -> None:
        with self.assertRaises(ValueError):
            flavor_host({'flavor': 'ghec', 'host': 'example.com'}, 'p')

    def test_ghes_uses_host_verbatim(self) -> None:
        self.assertEqual(
            flavor_host({'flavor': 'ghes', 'host': 'git.example.com'}, 'p'),
            'git.example.com',
        )
