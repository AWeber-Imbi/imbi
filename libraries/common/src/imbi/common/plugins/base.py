"""Plugin base classes and shared data models."""

import abc
import datetime
import typing

import pydantic


class PluginOption(pydantic.BaseModel):
    name: str
    label: str
    description: str | None = None
    type: typing.Literal['string', 'integer', 'boolean', 'secret'] = 'string'
    required: bool = False
    default: str | int | bool | None = None
    choices: list[str] | None = None


class CredentialField(pydantic.BaseModel):
    name: str
    label: str
    description: str | None = None
    required: bool = True


class DataType(pydantic.BaseModel):
    name: str
    label: str
    secret: bool = False


class PluginManifest(pydantic.BaseModel):
    slug: str
    name: str
    description: str | None = None
    plugin_type: typing.Literal['configuration', 'logs']
    api_version: int = 1
    cacheable: bool = True
    options: list[PluginOption] = []
    credentials: list[CredentialField] = []
    data_types: list[DataType] = []


class PluginContext(pydantic.BaseModel):
    project_id: str
    project_slug: str
    org_slug: str
    environment: str | None = None
    assignment_options: dict[str, typing.Any] = {}


class ConfigValue(pydantic.BaseModel):
    data_type: str
    value: str
    secret: bool = False


class ConfigKey(pydantic.BaseModel):
    key: str
    data_type: str
    last_modified: datetime.datetime | None = None
    secret: bool = False


class ConfigKeyWithValue(ConfigKey):
    value: str


class LogFilter(pydantic.BaseModel):
    field: str
    op: typing.Literal['eq', 'ne', 'contains', 'starts_with', 'regex']
    value: str


class LogQuery(pydantic.BaseModel):
    start_time: datetime.datetime
    end_time: datetime.datetime
    filters: list[LogFilter] = []
    limit: int = 100
    cursor: str | None = None


class LogEntry(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')

    timestamp: datetime.datetime
    message: str
    level: str | None = None
    raw: dict[str, typing.Any] = {}


class LogResult(pydantic.BaseModel):
    entries: list[LogEntry]
    next_cursor: str | None = None
    total: int | None = None


class ConfigurationPlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.
    """

    manifest: PluginManifest

    @abc.abstractmethod
    async def list_keys(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[ConfigKey]: ...

    @abc.abstractmethod
    async def get_values(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        keys: list[str] | None = None,
    ) -> list[ConfigKeyWithValue]: ...

    @abc.abstractmethod
    async def set_value(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
        value: ConfigValue,
    ) -> ConfigKey: ...

    @abc.abstractmethod
    async def delete_key(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
    ) -> None: ...


class LogsPlugin(abc.ABC):
    manifest: PluginManifest

    @abc.abstractmethod
    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult: ...

    @abc.abstractmethod
    async def schema(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[dict[str, typing.Any]]: ...
