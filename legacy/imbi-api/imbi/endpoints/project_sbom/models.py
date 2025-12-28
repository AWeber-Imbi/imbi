from __future__ import annotations

import datetime
import enum
import functools
import typing

import pydantic

BOMRef = typing.Annotated[str, pydantic.StringConstraints(min_length=1)]
PackageURL = typing.Annotated[str,
                              pydantic.StringConstraints(pattern=r'^pkg:')]
VersionMap = typing.MutableMapping[str, int]


class Dependency(pydantic.BaseModel):
    ref: BOMRef
    depends_on: list[BOMRef] = pydantic.Field(default_factory=list,
                                              alias='dependsOn')


class ExternalReference(pydantic.BaseModel):
    url: str
    type: str


class Component(pydantic.BaseModel):
    name: str
    bom_ref: typing.Union[BOMRef, None] = pydantic.Field(default=None,
                                                         alias='bom-ref')
    purl: typing.Union[PackageURL, None] = pydantic.Field(default=None,
                                                          frozen=True)
    version: typing.Union[str, None] = None
    external_references: list[ExternalReference] = pydantic.Field(
        default_factory=list, alias='externalReferences')

    @functools.cached_property
    def package_purl(self) -> typing.Union[str, None]:
        """Package URL without trailing info (eg, version, fragment, etc)"""
        return self.purl.partition('@')[0] if self.purl else None

    @property
    def home_page(self) -> typing.Union[str, None]:
        refs: dict[str, str] = {}
        for reference in self.external_references:
            refs[reference.type] = reference.url
        for ref_type in ['website', 'documentation', 'release-notes']:
            if page := refs.get(ref_type):
                return page
        return None


class SBOMMetadata(pydantic.BaseModel):
    component: typing.Union[Component, None] = None
    timestamp: typing.Union[datetime.datetime, None] = None


class SBOMSpecVersion(str, enum.Enum):
    V_1_5 = '1.5'
    V_1_6 = '1.6'


class SBOM(pydantic.BaseModel):
    bom_format: str = pydantic.Field(alias='bomFormat', pattern='CycloneDX')
    spec_version: SBOMSpecVersion = pydantic.Field(alias='specVersion')
    metadata: SBOMMetadata = pydantic.Field(default_factory=SBOMMetadata)
    components: list[Component] = pydantic.Field(default_factory=list)
    dependencies: list[Dependency] = pydantic.Field(default_factory=list)
