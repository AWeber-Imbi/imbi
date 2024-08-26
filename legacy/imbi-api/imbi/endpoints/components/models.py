from __future__ import annotations

import enum
import typing_extensions as typing

import pydantic

from imbi import semver, errors
from imbi.endpoints import base


class ComponentStatus(str, enum.Enum):
    ACTIVE = 'Active'
    DEPRECATED = 'Deprecated'
    FORBIDDEN = 'Forbidden'


class ProjectComponentStatus(str, enum.Enum):
    UNSCORED = 'Unscored'
    UP_TO_DATE = 'Up-to-date'
    OUTDATED = 'Outdated'
    DEPRECATED = 'Deprecated'
    FORBIDDEN = 'Forbidden'


# these are considered "out of date" for scoring purposes
OUTDATED_COMPONENT_STATUSES = frozenset((
    ProjectComponentStatus.DEPRECATED.value,
    ProjectComponentStatus.FORBIDDEN.value,
    ProjectComponentStatus.OUTDATED.value,
))

# Describes the expected `stats` dict for ProjectStatus.calculate
ProjectStatusCalculateStats = typing.TypedDict(
    'ProjectStatusCalculateStats',
    {e.value: int
     for e in ProjectComponentStatus},
    total=False,
)


class ProjectStatus(int, enum.Enum):
    """Component Score project fact values"""
    OKAY = 100
    NEEDS_WORK = 80
    UNACCEPTABLE = 20

    @classmethod
    def calculate(cls, stats: ProjectStatusCalculateStats) -> typing.Self:
        deprecated = stats[ProjectComponentStatus.DEPRECATED.value]
        forbidden = stats[ProjectComponentStatus.FORBIDDEN.value]
        outdated = stats[ProjectComponentStatus.OUTDATED.value]
        up_to_date = stats[ProjectComponentStatus.UP_TO_DATE.value]
        if not deprecated and not forbidden and not outdated:
            return cls.OKAY
        if not forbidden and (up_to_date > outdated or deprecated):
            return cls.NEEDS_WORK
        return cls.UNACCEPTABLE


class Component(pydantic.BaseModel):
    package_url: str = pydantic.constr(pattern=r'^pkg:')
    name: str
    status: ComponentStatus
    icon_class: str
    active_version: typing.Union[semver.VersionRange, None]
    home_page: typing.Union[str, None]


class ComponentToken(base.PaginationToken):
    """Pagination token that includes the starting package URL"""
    def __init__(self, *, starting_package: str = '', **kwargs) -> None:
        super().__init__(starting_package=starting_package, **kwargs)

    def with_first(self, value: dict[str, object]) -> typing.Self:
        kwargs = self.as_dict(starting_package=value['package_url'])
        return ComponentToken(**kwargs)


class ProjectComponentsToken(base.PaginationToken):
    """Pagination token that includes the starting package URL and project"""
    def __init__(self,
                 *,
                 starting_package: str = '',
                 project_id: int | str,
                 **kwargs) -> None:
        try:
            project_id = int(project_id)
        except ValueError:
            raise errors.BadRequest('Invalid project id %r, expected integer',
                                    project_id)
        super().__init__(starting_package=starting_package,
                         project_id=project_id,
                         **kwargs)

    def with_first(self, value: dict[str, object]) -> typing.Self:
        kwargs = self.as_dict(starting_package=value['package_url'])
        return ProjectComponentsToken(**kwargs)
