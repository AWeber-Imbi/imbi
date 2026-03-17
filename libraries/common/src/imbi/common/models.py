import datetime
import typing

import cypherantic
import pydantic
import slugify
from jsonschema_models import models as schema_models

__all__ = [
    'MODEL_TYPES',
    'Blueprint',
    'BlueprintAssignment',
    'BlueprintEdge',
    'Environment',
    'LinkDefinition',
    'Node',
    'Organization',
    'Project',
    'ProjectType',
    'RelationshipLink',
    'Schema',
    'Team',
]

Schema = schema_models.Schema


class Blueprint(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    slug: str | None = None
    type: typing.Literal['Team', 'Environment', 'ProjectType', 'Project']
    description: str | None = None
    enabled: bool = True
    priority: int = 0
    filter: dict[str, typing.Any] | None = None
    json_schema: Schema
    version: int = 0

    @pydantic.model_validator(mode='after')
    def generate_and_validate_slug(self) -> typing.Self:
        """Generate slug from name if not provided and validate it."""
        if self.slug is None:
            self.slug = slugify.slugify(self.name)
        else:
            self.slug = self.slug.lower()

        # Validate slug format
        if not self.slug:
            raise ValueError('Slug cannot be empty')
        if not all(c.islower() or c.isdigit() or c == '-' for c in self.slug):
            raise ValueError(
                'Slug must contain only lowercase letters, '
                'numbers, and hyphens'
            )
        return self

    @pydantic.field_validator('json_schema', mode='before')
    @classmethod
    def validate_json_schema(cls, value: typing.Any) -> Schema:
        if isinstance(value, str):
            return Schema.model_validate_json(value)
        elif isinstance(value, dict):
            return Schema.model_validate(value)
        elif isinstance(value, Schema):
            return value
        raise ValueError('Invalid JSON Schema value')

    @pydantic.field_serializer('json_schema')
    def serialize_json_schema(self, value: Schema) -> str:
        return value.model_dump_json(indent=0)


class BlueprintAssignment(pydantic.BaseModel):
    cypherantic_config: typing.ClassVar[cypherantic.RelationshipConfig] = (
        cypherantic.RelationshipConfig(rel_type='BLUEPRINT')
    )
    priority: int = 0


class BlueprintEdge(typing.NamedTuple):
    node: Blueprint
    properties: BlueprintAssignment


class RelationshipLink(pydantic.BaseModel):
    """A hypermedia-style link to related resources."""

    href: str
    count: int


class Node(pydantic.BaseModel):
    """Base model for Cypherantic nodes.

    The `icon` attribute can either be a URL or a CSS class name

    """

    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    created_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    updated_at: datetime.datetime | None = None


class Organization(Node):
    pass


class Team(Node):
    organization: typing.Annotated[
        Organization,
        cypherantic.Relationship(rel_type='BELONGS_TO', direction='OUTGOING'),
    ]


class Environment(Node):
    label_color: typing.Annotated[
        str | None,
        pydantic.Field(
            default=None,
            pattern=r'^#[0-9A-Fa-f]{6}$',
            description='Hex color for environment labels (e.g. #3B82F6)',
        ),
    ]

    organization: typing.Annotated[
        Organization,
        cypherantic.Relationship(rel_type='BELONGS_TO', direction='OUTGOING'),
    ]


class ProjectType(Node):
    organization: typing.Annotated[
        Organization,
        cypherantic.Relationship(rel_type='BELONGS_TO', direction='OUTGOING'),
    ]


class LinkDefinition(Node):
    """Defines available link types for projects in an org.

    Each definition describes one kind of external link
    (e.g. GitHub repository, Grafana dashboard) including
    display metadata and an optional URL template.

    """

    url_template: str | None = None
    organization: typing.Annotated[
        Organization,
        cypherantic.Relationship(
            rel_type='BELONGS_TO',
            direction='OUTGOING',
        ),
    ]


class Project(Node):
    team: typing.Annotated[
        Team,
        cypherantic.Relationship(
            rel_type='OWNED_BY',
            direction='OUTGOING',
        ),
    ]
    project_type: typing.Annotated[
        ProjectType,
        cypherantic.Relationship(
            rel_type='TYPE',
            direction='OUTGOING',
        ),
    ]
    environments: typing.Annotated[
        list[Environment],
        cypherantic.Relationship(
            rel_type='DEPLOYED_IN',
            direction='OUTGOING',
        ),
    ] = []
    links: dict[str, pydantic.HttpUrl] = {}
    identifiers: dict[str, int | str] = {}

    # Denormalized for composite uniqueness constraint in Neo4j.
    # Not exposed in API responses; kept in sync by the API layer.
    project_type_slug: typing.Annotated[
        str,
        pydantic.Field(exclude=True),
    ] = ''


# Model type mapping for schema generation
MODEL_TYPES: dict[str, type[pydantic.BaseModel]] = {
    'Environment': Environment,
    'LinkDefinition': LinkDefinition,
    'Organization': Organization,
    'Project': Project,
    'ProjectType': ProjectType,
    'Team': Team,
}
