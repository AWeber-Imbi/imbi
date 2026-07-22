import os
import unittest
import unittest.mock

import pydantic

from imbi.common.api import settings


class SettingsTests(unittest.TestCase):
    def test_loads_from_environment(self) -> None:
        env = {
            'IMBI_CLIENT_API_BASE_URL': 'https://imbi.example.com/',
            'IMBI_CLIENT_API_TOKEN': 'secret-token',
            'IMBI_CLIENT_USER_AGENT': 'imbi-gateway/9.9.9',
        }
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            s = settings.Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertEqual('https://imbi.example.com/', str(s.api_base_url))
        self.assertEqual('secret-token', s.api_token.get_secret_value())
        self.assertEqual('imbi-gateway/9.9.9', s.user_agent)

    def test_api_token_is_masked_in_repr(self) -> None:
        env = {'IMBI_CLIENT_API_TOKEN': 'super-secret'}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            s = settings.Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertNotIn('super-secret', repr(s))
        self.assertNotIn('super-secret', str(s.api_token))
        self.assertEqual('super-secret', s.api_token.get_secret_value())

    def test_defaults(self) -> None:
        with unittest.mock.patch.dict(
            os.environ, {'IMBI_CLIENT_API_TOKEN': 't'}, clear=True
        ):
            s = settings.Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertEqual('http://imbi-api:8000/', str(s.api_base_url))
        self.assertIsNone(s.user_agent)

    def test_missing_token_raises_validation_error(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(pydantic.ValidationError):
                settings.Settings(_env_file=None)  # type: ignore[call-arg]

    def test_case_insensitive_env(self) -> None:
        env = {'imbi_client_api_token': 'lowercase-token'}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            s = settings.Settings(_env_file=None)  # type: ignore[call-arg]
        self.assertEqual('lowercase-token', s.api_token.get_secret_value())
