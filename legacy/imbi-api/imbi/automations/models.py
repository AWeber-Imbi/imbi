import dataclasses
import typing


@dataclasses.dataclass
class CookieCutter:
    name: str
    project_type_id: int
    url: str


@dataclasses.dataclass
class Namespace:
    gitlab_group_name: typing.Union[str, None]
    name: str
    slug: str


@dataclasses.dataclass
class ProjectType:
    id: int
    environment_urls: bool
    gitlab_project_prefix: typing.Union[str, None]
    name: str
    slug: str


@dataclasses.dataclass
class Project:
    description: typing.Union[str, None]
    gitlab_project_id: typing.Union[int, None]
    id: int
    name: str
    namespace: Namespace
    project_type: ProjectType
    slug: str
