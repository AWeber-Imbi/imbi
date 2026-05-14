"""Pydantic settings for configuring the Imbi API client."""

import pydantic
import pydantic_settings

from imbi_common import settings as common_settings


class Settings(pydantic_settings.BaseSettings):
    """Configuration for `imbi_common.api.client.Imbi`.

    Values are loaded from environment variables prefixed with
    ``IMBI_CLIENT_``:

    - ``IMBI_CLIENT_API_BASE_URL`` — root URL of the Imbi API.
      Defaults to ``http://imbi-api:8000``.
    - ``IMBI_CLIENT_API_TOKEN`` — bearer token sent on every request.
      Required; instantiation raises ``ValidationError`` when unset.
    - ``IMBI_CLIENT_USER_AGENT`` — optional ``User-Agent`` override.
      When unset, the client falls back to ``imbi-common/{version}``.
    """

    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_CLIENT_',
    )

    api_base_url: pydantic.HttpUrl = pydantic.HttpUrl('http://imbi-api:8000')
    api_token: pydantic.SecretStr
    user_agent: str | None = None
