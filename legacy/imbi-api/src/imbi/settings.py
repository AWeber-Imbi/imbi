import urllib.parse

import pydantic
import pydantic_settings

BASE_SETTINGS = {
    'case_sensitive': False,
    'env_file': '.env',
    'env_file_encoding': 'utf-8',
    'extra': 'ignore',
}


class Neo4j(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix='NEO4J_', **BASE_SETTINGS
    )
    url: pydantic.AnyUrl = pydantic.AnyUrl('neo4j://localhost:7687')
    user: str | None = None
    password: str | None = None
    database: str = 'neo4j'
    keep_alive: bool = True
    liveness_check_timeout: int = 60
    max_connection_lifetime: int = 300

    @pydantic.model_validator(mode='after')
    def extract_credentials_from_url(self) -> 'Neo4j':
        """Extract username/password from URL and strip them from the URL.

        If the URL contains embedded credentials (e.g.,
        neo4j://username:password@localhost:7687), extract them and set
        the user and password fields, then clean the URL.

        """
        if self.url.username and not self.user:
            # Decode URL-encoded username
            self.user = urllib.parse.unquote(self.url.username)

        if self.url.password and not self.password:
            # Decode URL-encoded password
            self.password = urllib.parse.unquote(self.url.password)

        # Strip credentials from URL if present
        if self.url.username or self.url.password:
            # Rebuild URL without credentials
            scheme = self.url.scheme
            host = self.url.host or 'localhost'
            port = self.url.port or 7687
            path = self.url.path or ''

            # Construct clean URL (no trailing slash if no path)
            if path:
                clean_url = f'{scheme}://{host}:{port}{path}'
            else:
                clean_url = f'{scheme}://{host}:{port}'
            self.url = pydantic.AnyUrl(clean_url)

        return self


class ServerConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix='IMBI_', **BASE_SETTINGS
    )
    environment: str = 'development'
    host: str = 'localhost'
    port: int = 8000
