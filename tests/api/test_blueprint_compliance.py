"""Tests for blueprint-compliance remediation."""

from __future__ import annotations

import unittest
from unittest import mock

from imbi.api import blueprint_compliance
from imbi.common import graph

_MODULE = 'imbi.api.blueprint_compliance'


class RemediateBlueprintTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)

    async def test_invalid_id_fails(self) -> None:
        result = await blueprint_compliance.remediate_blueprint(
            self.db, 'p1', ['service'], 'bogus-no-colon'
        )
        self.assertEqual('failed', result.status)

    async def test_unsafe_property_name_fails(self) -> None:
        result = await blueprint_compliance.remediate_blueprint(
            self.db, 'p1', ['service'], 'remove-stale:bad name'
        )
        self.assertEqual('failed', result.status)

    async def test_remove_stale_noop_when_absent(self) -> None:
        with mock.patch(f'{_MODULE}._fetch_project_props', return_value={}):
            result = await blueprint_compliance.remediate_blueprint(
                self.db, 'p1', ['service'], 'remove-stale:foo'
            )
        self.assertEqual('noop', result.status)
        self.db.execute.assert_not_awaited()

    async def test_remove_stale_fixes_when_present(self) -> None:
        with (
            mock.patch(
                f'{_MODULE}._fetch_project_props', return_value={'foo': 'v'}
            ),
            mock.patch(f'{_MODULE}.project_blueprints', return_value=[]),
            mock.patch(f'{_MODULE}._applicable_blueprints', return_value=[]),
            mock.patch(
                f'{_MODULE}._stale_blueprint_properties', return_value=['foo']
            ),
        ):
            result = await blueprint_compliance.remediate_blueprint(
                self.db, 'p1', ['service'], 'remove-stale:foo'
            )
        self.assertEqual('fixed', result.status)
        self.db.execute.assert_awaited()

    async def test_remove_stale_refuses_when_no_longer_stale(self) -> None:
        # The property is still set but the blueprint config changed so it
        # is now valid again -> must not be wiped.
        with (
            mock.patch(
                f'{_MODULE}._fetch_project_props', return_value={'foo': 'v'}
            ),
            mock.patch(f'{_MODULE}.project_blueprints', return_value=[]),
            mock.patch(f'{_MODULE}._applicable_blueprints', return_value=[]),
            mock.patch(
                f'{_MODULE}._stale_blueprint_properties', return_value=[]
            ),
        ):
            result = await blueprint_compliance.remediate_blueprint(
                self.db, 'p1', ['service'], 'remove-stale:foo'
            )
        self.assertEqual('failed', result.status)
        self.db.execute.assert_not_awaited()

    async def test_set_default_noop_when_set(self) -> None:
        with mock.patch(
            f'{_MODULE}._fetch_project_props', return_value={'foo': 'v'}
        ):
            result = await blueprint_compliance.remediate_blueprint(
                self.db, 'p1', ['service'], 'set-default:foo'
            )
        self.assertEqual('noop', result.status)

    async def test_set_default_fails_without_default(self) -> None:
        with (
            mock.patch(f'{_MODULE}._fetch_project_props', return_value={}),
            mock.patch(f'{_MODULE}.project_blueprints', return_value=[]),
            mock.patch(f'{_MODULE}._applicable_blueprints', return_value=[]),
            mock.patch(f'{_MODULE}._blueprint_default', return_value=None),
        ):
            result = await blueprint_compliance.remediate_blueprint(
                self.db, 'p1', ['service'], 'set-default:foo'
            )
        self.assertEqual('failed', result.status)

    async def test_set_default_fixes_when_missing(self) -> None:
        with (
            mock.patch(f'{_MODULE}._fetch_project_props', return_value={}),
            mock.patch(f'{_MODULE}.project_blueprints', return_value=[]),
            mock.patch(f'{_MODULE}._applicable_blueprints', return_value=[]),
            mock.patch(
                f'{_MODULE}._blueprint_default', return_value='the-default'
            ),
        ):
            result = await blueprint_compliance.remediate_blueprint(
                self.db, 'p1', ['service'], 'set-default:foo'
            )
        self.assertEqual('fixed', result.status)
        self.db.execute.assert_awaited()
