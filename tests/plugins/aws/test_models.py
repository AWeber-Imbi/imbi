"""Tests for the AwsAccount Pydantic model."""

import unittest

from imbi_plugin_aws.models import AwsAccount


class AwsAccountTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        account = AwsAccount(
            id='nano-id',
            account_id='123456789012',
            name='Production us-east-1',
            default_role_name='PowerUserAccess',
            default_region='us-east-1',
            tags={'tier': 'prod'},
        )
        restored = AwsAccount.model_validate(account.model_dump())
        self.assertEqual(restored.account_id, '123456789012')
        self.assertEqual(restored.tags, {'tier': 'prod'})

    def test_account_id_must_be_12_digits(self) -> None:
        with self.assertRaises(ValueError):
            AwsAccount(
                id='nano-id',
                account_id='12345',
                name='Bad',
            )

    def test_account_id_rejects_non_digits(self) -> None:
        with self.assertRaises(ValueError):
            AwsAccount(
                id='nano-id',
                account_id='abc456789012',
                name='Bad',
            )
