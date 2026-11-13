"""``caller_org_slugs`` for a scheduler request."""

import unittest
from unittest import mock

from imbi.api.endpoints import _helpers
from imbi.common import models
from imbi.common.auth import permissions


class CallerOrgSlugsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_request_keeps_only_shared_orgs(self) -> None:
        # The scheduler is in a, b, and c; the accountable user in a only.
        db = mock.AsyncMock()
        db.execute.side_effect = [
            [{'slug': '"a"'}, {'slug': '"b"'}, {'slug': '"c"'}],
            [{'slug': '"a"'}],
        ]
        auth = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-scheduler', display_name='Scheduler'
            ),
            auth_method='client_credentials',
            on_behalf_of=('User', 'email', 'dev@example.com'),
        )
        self.assertEqual({'a'}, await _helpers.caller_org_slugs(db, auth))
        self.assertEqual(
            {'who': 'dev@example.com'}, db.execute.await_args_list[1].args[1]
        )
