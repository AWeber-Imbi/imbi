"""Connection settings of the relational database."""

import pydantic
import pydantic_settings

from imbi.common import settings


class Database(pydantic_settings.BaseSettings):
    """The two logins of the application.

    ``DATABASE_URL`` is the ``imbi_app`` login and ``ADMIN_DATABASE_URL``
    is the ``imbi_admin`` login. The application has no URL for the
    owner or for ``imbi_maintenance``: only a deploy and the ETL use
    them.

    """

    model_config = settings.base_settings_config()

    database_url: pydantic.PostgresDsn = pydantic.PostgresDsn(
        'postgresql://imbi_app@localhost:5432/imbi'
    )
    admin_database_url: pydantic.PostgresDsn = pydantic.PostgresDsn(
        'postgresql://imbi_admin@localhost:5432/imbi'
    )
    database_min_pool_size: int = 2
    database_max_pool_size: int = 10
