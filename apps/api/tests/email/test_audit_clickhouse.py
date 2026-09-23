"""Email audit rows, written through the sink path to a live ClickHouse.

``email_audit`` was in ``imbi.common.iggy.TOPICS`` with no table behind it,
so every audit was published and then could never be inserted. Before the
Iggy move the direct insert failed the same way and the error was logged
and swallowed. Every other email test mocks ClickHouse, which is how that
went unnoticed. These write a real audit the way the sink does and read it
back.
"""

import datetime
import hashlib
import unittest
import uuid

from apps.api.tests import support
from imbi.api import email
from imbi.api.email import models
from imbi.common import clickhouse
from imbi.common.clickhouse import client


class EmailAuditClickhouseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # ``Clickhouse`` is a process-wide singleton bound to the loop that
        # opened it, and each test method gets its own loop, so take a
        # private instance and hand the previous one back afterwards. See
        # test_document_reads_sql for the failure this avoids.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        await clickhouse.setup_schema()

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def _read_back(self, entity_id: str) -> dict[str, object]:
        rows = await clickhouse.query(
            'SELECT * FROM email_audit'
            ' WHERE related_entity_id = {entity_id:String}',
            {'entity_id': entity_id},
        )
        self.assertEqual(1, len(rows))
        return rows[0]

    async def test_a_sent_email_is_audited_without_its_address(self) -> None:
        entity_id = str(uuid.uuid4())
        audit = models.EmailAudit(
            to_email='Someone@Example.com',
            template_name='password_reset',
            subject='Reset your password',
            status='sent',
            sent_at=datetime.datetime.now(datetime.UTC),
            user_id='user-1',
            related_entity_type='password_reset_token',
            related_entity_id=entity_id,
        )
        with support.sink_to_clickhouse():
            await email._save_audit(audit)

        row = await self._read_back(entity_id)
        self.assertEqual('password_reset', row['template_name'])
        self.assertEqual('sent', row['status'])
        self.assertEqual(
            hashlib.sha256(b'someone@example.com').hexdigest(),
            row['to_email_hash'],
        )
        # `EmailStr` lowercases the domain but keeps the local part's case.
        self.assertEqual('example.com', row['to_email_domain'])
        self.assertNotIn('to_email', row)
        for address in (
            'Someone@Example.com',
            'Someone@example.com',
            'someone@example.com',
        ):
            self.assertNotIn(address, row.values())

    async def test_unset_optional_fields_land_as_empty_strings(self) -> None:
        # `EmailAudit` sends null for its optional fields and the columns are
        # not Nullable, so this pins the server's null-as-default behaviour
        # the table depends on.
        entity_id = str(uuid.uuid4())
        audit = models.EmailAudit(
            to_email='someone@example.com',
            template_name='password_reset',
            subject='Reset your password',
            status='failed',
            error_message=None,
            sent_at=datetime.datetime.now(datetime.UTC),
            related_entity_id=entity_id,
        )
        with support.sink_to_clickhouse():
            await email._save_audit(audit)

        row = await self._read_back(entity_id)
        self.assertEqual('failed', row['status'])
        self.assertEqual('', row['error_message'])
        self.assertEqual('', row['user_id'])
        self.assertEqual('', row['related_entity_type'])
