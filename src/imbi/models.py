import pydantic
from jsonschema_models.models import Schema


class Blueprint(pydantic.BaseModel):
    name: str
    slug: str
    description: str
    json_schema: Schema


class Namespace(pydantic.BaseModel):
    name: str
    description: str
    icon_class: str
    slug: str


class ProjectType(pydantic.BaseModel):
    name: str
    plural_name: str
    description: str
    icon_class: str
    environment_urls: bool
    slug: str


class Project(pydantic.BaseModel):
    id: int
    name: str
    slug: str
    description: str
    environments: list[str]
    links: dict[str, pydantic.HttpUrl]
    urls: dict[str, pydantic.HttpUrl]
    identifiers: dict[str, int | str]
