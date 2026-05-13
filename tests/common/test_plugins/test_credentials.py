"""Tests for imbi_common.plugins.credentials."""

import json
import unittest
from unittest import mock

from cryptography import fernet

from imbi_common.auth import encryption
from imbi_common.plugins import base as plugin_base
from imbi_common.plugins import credentials, errors, registry


def _make_entry(
    auth_type: str = 'api_token',
    credentials_fields: list[plugin_base.CredentialField] | None = None,
) -> registry.RegistryEntry:
    """Build a minimal ``RegistryEntry`` for the given auth type."""
    manifest = plugin_base.PluginManifest(
        slug='example',
        name='Example',
        plugin_type='configuration',
        auth_type=auth_type,  # type: ignore[arg-type]
        credentials=credentials_fields or [],
    )

    class _Stub(plugin_base.ConfigurationPlugin):
        manifest = plugin_base.PluginManifest(
            slug='example',
            name='Example',
            plugin_type='configuration',
        )

        async def get_configuration(  # type: ignore[override]
            self, ctx, credentials
        ):
            return []

    return registry.RegistryEntry(
        handler_cls=_Stub,
        manifest=manifest,
        package_name='imbi-common-tests',
        package_version='0.0.0',
    )


class _EncryptionFixture(unittest.IsolatedAsyncioTestCase):
    """Base class that wires a real Fernet key into TokenEncryption."""

    def setUp(self) -> None:
        encryption.TokenEncryption.reset_instance()
        self.test_key = fernet.Fernet.generate_key().decode('ascii')
        self._patcher = mock.patch('imbi_common.settings.get_auth_settings')
        mock_settings = self._patcher.start()
        mock_settings.return_value.encryption_key = self.test_key

    def tearDown(self) -> None:
        self._patcher.stop()
        encryption.TokenEncryption.reset_instance()

    def encrypt(self, plaintext: str) -> str:
        result = encryption.TokenEncryption.get_instance().encrypt(plaintext)
        assert result is not None
        return result


def _mock_db_returning(creds_value: object) -> mock.AsyncMock:
    """Build a mock ``Graph`` whose ``execute`` returns one record."""
    db = mock.AsyncMock()
    db.execute = mock.AsyncMock(return_value=[{'creds': creds_value}])
    return db


def _mock_db_empty() -> mock.AsyncMock:
    db = mock.AsyncMock()
    db.execute = mock.AsyncMock(return_value=[])
    return db


def _mock_db_with_application(
    client_id: object, client_secret: object
) -> mock.AsyncMock:
    db = mock.AsyncMock()
    db.execute = mock.AsyncMock(
        return_value=[{'client_id': client_id, 'client_secret': client_secret}]
    )
    return db


class GetPluginCredentialsAPITokenTestCase(_EncryptionFixture):
    async def test_returns_decrypted_dict(self) -> None:
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        encrypted = self.encrypt(json.dumps({'token': 'secret-value'}))
        db = _mock_db_returning(encrypted)

        result = await credentials.get_plugin_credentials(
            db, 'plugin-1', entry
        )

        self.assertEqual(result, {'token': 'secret-value'})

    async def test_aws_iam_ic_routes_to_configuration_path(self) -> None:
        entry = _make_entry(
            'aws-iam-ic',
            [plugin_base.CredentialField(name='client_id', label='ID')],
        )
        encrypted = self.encrypt(json.dumps({'client_id': 'abc'}))
        db = _mock_db_returning(encrypted)

        result = await credentials.get_plugin_credentials(
            db, 'plugin-1', entry
        )

        self.assertEqual(result, {'client_id': 'abc'})

    async def test_missing_record_raises_missing_credentials(self) -> None:
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        db = _mock_db_empty()

        with self.assertRaises(errors.PluginCredentialsMissing) as ctx:
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

        self.assertIn('token', str(ctx.exception))

    async def test_null_record_raises_missing_credentials(self) -> None:
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        db = _mock_db_returning(None)

        with self.assertRaises(errors.PluginCredentialsMissing):
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

    async def test_required_field_with_null_value_raises(self) -> None:
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        # ``token`` present but JSON-null should be treated as missing.
        encrypted = self.encrypt(json.dumps({'token': None}))
        db = _mock_db_returning(encrypted)

        with self.assertRaises(errors.PluginCredentialsMissing):
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

    async def test_optional_field_not_required(self) -> None:
        entry = _make_entry(
            'api_token',
            [
                plugin_base.CredentialField(
                    name='token', label='Token', required=False
                ),
            ],
        )
        encrypted = self.encrypt(json.dumps({}))
        db = _mock_db_returning(encrypted)

        result = await credentials.get_plugin_credentials(
            db, 'plugin-1', entry
        )
        self.assertEqual(result, {})

    async def test_decrypt_failure_treated_as_missing(self) -> None:
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        # Build ciphertext under a *different* key — decryption will fail
        # against the current TokenEncryption instance.
        other_key = fernet.Fernet.generate_key().decode('ascii')
        bad_encrypted = encryption.TokenEncryption(other_key).encrypt(
            json.dumps({'token': 'x'})
        )
        db = _mock_db_returning(bad_encrypted)

        with self.assertRaises(errors.PluginCredentialsMissing):
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

    async def test_invalid_json_blob_treated_as_missing(self) -> None:
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        encrypted = self.encrypt('not-json')
        db = _mock_db_returning(encrypted)

        with self.assertRaises(errors.PluginCredentialsMissing):
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

    async def test_decrypt_raises_logged_and_treated_as_missing(
        self,
    ) -> None:
        """When ``decrypt`` itself raises, we log and treat as missing."""
        entry = _make_entry(
            'api_token',
            [plugin_base.CredentialField(name='token', label='Token')],
        )
        db = _mock_db_returning('some-encrypted')
        with mock.patch.object(
            encryption.TokenEncryption,
            'decrypt',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertLogs(
                'imbi_common.plugins.credentials', level='WARNING'
            ) as logs:
                with self.assertRaises(errors.PluginCredentialsMissing):
                    await credentials.get_plugin_credentials(
                        db, 'plugin-1', entry
                    )
        self.assertTrue(
            any('decrypt failed' in m for m in logs.output),
            f'expected a decrypt-failed log, got {logs.output!r}',
        )

    async def test_strips_null_values_from_result(self) -> None:
        entry = _make_entry(
            'api_token',
            [
                plugin_base.CredentialField(name='token', label='Token'),
                plugin_base.CredentialField(
                    name='extra', label='Extra', required=False
                ),
            ],
        )
        encrypted = self.encrypt(json.dumps({'token': 'real', 'extra': None}))
        db = _mock_db_returning(encrypted)

        result = await credentials.get_plugin_credentials(
            db, 'plugin-1', entry
        )
        self.assertEqual(result, {'token': 'real'})


class GetPluginCredentialsApplicationTestCase(_EncryptionFixture):
    async def test_oauth2_returns_client_credentials(self) -> None:
        entry = _make_entry('oauth2')
        encrypted_secret = self.encrypt('shh')
        db = _mock_db_with_application('client-abc', encrypted_secret)

        result = await credentials.get_plugin_credentials(
            db, 'plugin-1', entry
        )

        self.assertEqual(
            result, {'client_id': 'client-abc', 'client_secret': 'shh'}
        )

    async def test_no_linked_application_raises(self) -> None:
        entry = _make_entry('oauth2')
        db = _mock_db_empty()

        with self.assertRaises(errors.PluginCredentialsMissing) as ctx:
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)
        self.assertIn('ServiceApplication', str(ctx.exception))

    async def test_missing_client_id_raises(self) -> None:
        entry = _make_entry('oauth2')
        db = _mock_db_with_application(None, self.encrypt('shh'))

        with self.assertRaises(errors.PluginCredentialsMissing):
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

    async def test_missing_client_secret_raises(self) -> None:
        entry = _make_entry('oauth2')
        db = _mock_db_with_application('client-abc', None)

        with self.assertRaises(errors.PluginCredentialsMissing):
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)

    async def test_secret_decrypt_failure_raises(self) -> None:
        """If decrypt returns None, treat the secret as missing.

        ``TokenEncryption.decrypt`` swallows fernet errors and returns
        ``None`` rather than raising, so the credential code path falls
        through to the ``no client_secret`` branch.
        """
        entry = _make_entry('oauth2')
        other_key = fernet.Fernet.generate_key().decode('ascii')
        bad_secret = encryption.TokenEncryption(other_key).encrypt('shh')
        db = _mock_db_with_application('client-abc', bad_secret)

        with self.assertRaises(errors.PluginCredentialsMissing) as ctx:
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)
        self.assertIn('no client_secret', str(ctx.exception))

    async def test_secret_decrypt_raises_is_wrapped(self) -> None:
        """If decrypt raises, surface 'could not be decrypted'."""
        entry = _make_entry('oauth2')
        db = _mock_db_with_application('client-abc', 'some-encrypted')
        with mock.patch.object(
            encryption.TokenEncryption,
            'decrypt',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(errors.PluginCredentialsMissing) as ctx:
                await credentials.get_plugin_credentials(db, 'plugin-1', entry)
            self.assertIn('could not be decrypted', str(ctx.exception))

    async def test_empty_secret_after_decrypt_raises(self) -> None:
        entry = _make_entry('oauth2')
        encrypted_empty = self.encrypt('')
        db = _mock_db_with_application('client-abc', encrypted_empty)

        with self.assertRaises(errors.PluginCredentialsMissing) as ctx:
            await credentials.get_plugin_credentials(db, 'plugin-1', entry)
        self.assertIn('no client_secret', str(ctx.exception))


class PatchPluginConfigurationTestCase(_EncryptionFixture):
    async def test_seeds_blob_when_empty_string(self) -> None:
        """An empty-string blob is treated like a missing blob."""
        db = _mock_db_returning('')

        keys = await credentials.patch_plugin_configuration(
            db, 'plugin-1', {'token': 'value'}
        )

        self.assertEqual(keys, ['token'])

    async def test_seeds_blob_when_absent(self) -> None:
        db = _mock_db_returning(None)

        keys = await credentials.patch_plugin_configuration(
            db, 'plugin-1', {'token': 'value'}
        )

        self.assertEqual(keys, ['token'])
        # second call to execute writes the SET statement
        self.assertEqual(db.execute.await_count, 2)
        write_args = db.execute.await_args_list[1].args
        params = write_args[1]
        # Round-trip the encrypted blob to confirm it stored what we
        # expect — proves patch encrypted with the same TokenEncryption.
        stored = json.loads(
            encryption.TokenEncryption.get_instance().decrypt(params['blob'])
        )
        self.assertEqual(stored, {'token': 'value'})

    async def test_merges_with_existing(self) -> None:
        existing = self.encrypt(json.dumps({'token': 'old', 'extra': 'keep'}))
        db = _mock_db_returning(existing)

        keys = await credentials.patch_plugin_configuration(
            db, 'plugin-1', {'token': 'new'}
        )

        self.assertEqual(sorted(keys), ['extra', 'token'])
        params = db.execute.await_args_list[1].args[1]
        stored = json.loads(
            encryption.TokenEncryption.get_instance().decrypt(params['blob'])
        )
        self.assertEqual(stored, {'token': 'new', 'extra': 'keep'})

    async def test_none_value_removes_key(self) -> None:
        existing = self.encrypt(json.dumps({'token': 'old', 'extra': 'keep'}))
        db = _mock_db_returning(existing)

        keys = await credentials.patch_plugin_configuration(
            db, 'plugin-1', {'token': None}
        )

        self.assertEqual(keys, ['extra'])
        params = db.execute.await_args_list[1].args[1]
        stored = json.loads(
            encryption.TokenEncryption.get_instance().decrypt(params['blob'])
        )
        self.assertEqual(stored, {'extra': 'keep'})

    async def test_empty_string_value_removes_key(self) -> None:
        existing = self.encrypt(json.dumps({'token': 'old', 'extra': 'keep'}))
        db = _mock_db_returning(existing)

        keys = await credentials.patch_plugin_configuration(
            db, 'plugin-1', {'token': ''}
        )

        self.assertEqual(keys, ['extra'])

    async def test_refuses_to_overwrite_undecryptable_blob(self) -> None:
        """A blob ciphered under another key decrypts to ``None``.

        That surfaces as a ``ValueError`` so the caller cannot silently
        overwrite corrupted credentials.
        """
        other_key = fernet.Fernet.generate_key().decode('ascii')
        bad = encryption.TokenEncryption(other_key).encrypt('whatever')
        db = _mock_db_returning(bad)

        with self.assertRaises(ValueError) as ctx:
            await credentials.patch_plugin_configuration(
                db, 'plugin-1', {'token': 'new'}
            )
        self.assertIn('decrypted to None', str(ctx.exception))

    async def test_refuses_when_decrypt_raises(self) -> None:
        """If decrypt raises, the read wraps it in a ValueError."""
        db = _mock_db_returning('some-text')
        with mock.patch.object(
            encryption.TokenEncryption,
            'decrypt',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(ValueError) as ctx:
                await credentials.patch_plugin_configuration(
                    db, 'plugin-1', {'token': 'new'}
                )
            self.assertIn('could not be decrypted', str(ctx.exception))

    async def test_refuses_to_overwrite_invalid_json(self) -> None:
        bad = self.encrypt('not-json-at-all')
        db = _mock_db_returning(bad)

        with self.assertRaises(ValueError) as ctx:
            await credentials.patch_plugin_configuration(
                db, 'plugin-1', {'token': 'new'}
            )
        self.assertIn('valid JSON', str(ctx.exception))

    async def test_refuses_to_overwrite_non_object_json(self) -> None:
        """JSON like ``[1, 2]`` or ``"hello"`` is not a plugin config."""
        bad = self.encrypt(json.dumps(['arr', 'ay']))
        db = _mock_db_returning(bad)

        with self.assertRaises(ValueError) as ctx:
            await credentials.patch_plugin_configuration(
                db, 'plugin-1', {'token': 'new'}
            )
        self.assertIn('must be', str(ctx.exception))

    async def test_decrypts_to_none_raises(self) -> None:
        """Garbage ciphertext decrypts to None — refuse to overwrite."""
        db = _mock_db_returning('not-fernet-text')

        with self.assertRaises(ValueError) as ctx:
            await credentials.patch_plugin_configuration(
                db, 'plugin-1', {'token': 'new'}
            )
        self.assertIn('decrypted to None', str(ctx.exception))


class GetPluginConfigurationKeysTestCase(_EncryptionFixture):
    async def test_returns_populated_keys(self) -> None:
        encrypted = self.encrypt(json.dumps({'token': 'real', 'empty': ''}))
        db = _mock_db_returning(encrypted)

        keys = await credentials.get_plugin_configuration_keys(db, 'plugin-1')

        self.assertEqual(keys, ['token'])

    async def test_empty_when_no_blob(self) -> None:
        db = _mock_db_returning(None)

        keys = await credentials.get_plugin_configuration_keys(db, 'plugin-1')

        self.assertEqual(keys, [])

    async def test_empty_when_no_records(self) -> None:
        db = _mock_db_empty()

        keys = await credentials.get_plugin_configuration_keys(db, 'plugin-1')

        self.assertEqual(keys, [])

    async def test_unreadable_blob_returns_empty(self) -> None:
        """An undecryptable blob is reported as ``[]`` (warning logged)."""
        other_key = fernet.Fernet.generate_key().decode('ascii')
        bad = encryption.TokenEncryption(other_key).encrypt('whatever')
        db = _mock_db_returning(bad)

        with self.assertLogs(
            'imbi_common.plugins.credentials', level='WARNING'
        ):
            keys = await credentials.get_plugin_configuration_keys(
                db, 'plugin-1'
            )

        self.assertEqual(keys, [])
