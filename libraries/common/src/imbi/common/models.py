import dataclasses
import datetime
import typing

import nanoid
import pydantic
import slugify
from jsonschema_models import models as schema_models

__all__ = [
    'Blueprint',
    'BlueprintAssignment',
    'BlueprintEdge',
    'BlueprintFilter',
    'Edge',
    'Embeddable',
    'Embedding',
    'Environment',
    'GraphModel',
    'LinkDefinition',
    'Node',
    'OperationLog',
    'Organization',
    'Project',
    'ProjectType',
    'RelationshipEdge',
    'RelationshipLink',
    'Schema',
    'Team',
    'ThirdPartyService',
]

Schema = schema_models.Schema


@dataclasses.dataclass(frozen=True, slots=True)
class Edge:
    """An edge between two nodes in the graph."""

    rel_type: str
    direction: typing.Literal['INCOMING', 'OUTGOING']


@dataclasses.dataclass(frozen=True, slots=True)
class Embeddable:
    """Marks a field for automatic embedding generation.

    Attach via ``typing.Annotated`` metadata, similar to
    ``Edge``.  Fields annotated with ``Embeddable`` are
    automatically embedded when nodes are created or merged.

    """

    model_name: str = 'text'
    chunk: bool = False
    mimetype: str = 'text/plain'


class GraphModel(pydantic.BaseModel):
    """Minimal base for any model stored as a graph vertex.

    Provides identity (``id``), timestamps, and
    ``extra='ignore'`` so AGE metadata is silently dropped.
    Subclass ``Node`` when you also need ``name``/``slug``.

    """

    model_config = pydantic.ConfigDict(extra='ignore')

    id: str = pydantic.Field(
        default_factory=nanoid.generate,
    )
    created_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    updated_at: datetime.datetime | None = None


class Node(GraphModel):
    """Graph node with business identity fields.

    The ``icon`` attribute can either be a URL or a CSS
    class name.

    """

    name: typing.Annotated[str, Embeddable()]
    slug: str
    description: typing.Annotated[
        str | None,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ] = None
    icon: pydantic.HttpUrl | str | None = None


class BlueprintFilter(pydantic.BaseModel):
    """Filter criteria for blueprint applicability.

    All fields use ``list[str]`` — a blueprint matches when the
    context value is contained in the list.  Multiple fields are
    ANDed together.  Omitted fields match everything.

    """

    model_config = pydantic.ConfigDict(extra='forbid')

    project_type: list[str] = []
    environment: list[str] = []


class RelationshipEdge(pydantic.BaseModel):
    """Base model for dynamic edge property models.

    Relationship blueprints extend this via
    ``pydantic.create_model`` to add data-driven fields.
    """

    model_config = pydantic.ConfigDict(extra='ignore')


class Blueprint(Node):
    # Overrides Node.slug to optional; model validator
    # below auto-generates slug from name at runtime.
    slug: str | None = None  # type: ignore[assignment]
    kind: typing.Literal['node', 'relationship'] = 'node'
    type: (
        typing.Literal[
            'Team',
            'Environment',
            'ProjectType',
            'Project',
            'Organization',
            'ThirdPartyService',
        ]
        | None
    ) = None
    source: str | None = None
    target: str | None = None
    edge: str | None = None
    enabled: bool = True
    priority: int = 0
    filter: BlueprintFilter | None = None
    json_schema: Schema
    version: int = 0

    @pydantic.model_validator(mode='after')
    def validate_kind_fields(self) -> typing.Self:
        """Validate kind-specific required fields."""
        if self.kind == 'node':
            if not self.type:
                raise ValueError('type is required for node blueprints')
            invalid = [
                f
                for f in ('source', 'target', 'edge')
                if getattr(self, f) is not None
            ]
            if invalid:
                raise ValueError(
                    f'{", ".join(invalid)} must be None for node blueprints'
                )
        else:
            if self.type is not None:
                raise ValueError(
                    'type must be None for relationship blueprints'
                )
            missing = [
                f for f in ('source', 'target', 'edge') if not getattr(self, f)
            ]
            if missing:
                raise ValueError(
                    f'{", ".join(missing)} required for '
                    f'relationship blueprints'
                )
        return self

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

    @pydantic.field_validator('filter', mode='before')
    @classmethod
    def validate_filter(
        cls,
        value: typing.Any,
    ) -> BlueprintFilter | None:
        if value is None:
            return None
        if isinstance(value, str):
            return BlueprintFilter.model_validate_json(value)
        if isinstance(value, dict):
            return BlueprintFilter.model_validate(value)
        if isinstance(value, BlueprintFilter):
            return value
        raise ValueError('Invalid filter value')

    @pydantic.field_serializer('filter')
    def serialize_filter(
        self,
        value: BlueprintFilter | None,
    ) -> str | None:
        if value is None:
            return None
        return value.model_dump_json()

    @pydantic.field_validator('json_schema', mode='before')
    @classmethod
    def validate_json_schema(
        cls,
        value: typing.Any,
    ) -> Schema:
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
    priority: int = 0


class BlueprintEdge(typing.NamedTuple):
    node: Blueprint
    properties: BlueprintAssignment


class RelationshipLink(pydantic.BaseModel):
    """A hypermedia-style link to related resources."""

    href: str
    count: int


class Organization(Node):
    pass


class Team(Node):
    organization: typing.Annotated[
        Organization,
        Edge(rel_type='BELONGS_TO', direction='OUTGOING'),
    ]


class Environment(Node):
    sort_order: int = 0

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
        Edge(rel_type='BELONGS_TO', direction='OUTGOING'),
    ]


class ProjectType(Node):
    organization: typing.Annotated[
        Organization,
        Edge(rel_type='BELONGS_TO', direction='OUTGOING'),
    ]


class ThirdPartyService(Node):
    organization: typing.Annotated[
        Organization,
        Edge(rel_type='BELONGS_TO', direction='OUTGOING'),
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
        Edge(
            rel_type='BELONGS_TO',
            direction='OUTGOING',
        ),
    ]


class Project(Node):
    team: typing.Annotated[
        Team,
        Edge(
            rel_type='OWNED_BY',
            direction='OUTGOING',
        ),
    ]
    project_types: typing.Annotated[
        list[ProjectType],
        Edge(
            rel_type='TYPE',
            direction='OUTGOING',
        ),
    ] = []
    environments: typing.Annotated[
        list[Environment],
        Edge(
            rel_type='DEPLOYED_IN',
            direction='OUTGOING',
        ),
    ] = []
    links: dict[str, pydantic.AnyUrl] = {}
    identifiers: dict[str, int | str | pydantic.AnyUrl] = {}


class Embedding(pydantic.BaseModel):
    """An embedding record from the relational table."""

    node_label: str
    node_id: str
    attribute: str
    chunk_index: int = 0
    model_name: str = 'text'
    chunk_text: str
    embedding: list[float]


_OPSLOG_ENTRY_TYPES = typing.Literal[
    'Configured',
    'Decommissioned',
    'Deployed',
    'Migrated',
    'Provisioned',
    'Restarted',
    'Rolled Back',
    'Scaled',
    'Upgraded',
]


class OperationLog(pydantic.BaseModel):
    """An operational event recorded in ClickHouse."""

    model_config = pydantic.ConfigDict(populate_by_name=True)

    id: str = pydantic.Field(default_factory=nanoid.generate)
    occurred_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    recorded_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    recorded_by: str
    performed_by: str | None = None
    completed_at: datetime.datetime | None = None
    project_id: str
    project_slug: str
    environment_slug: str
    entry_type: _OPSLOG_ENTRY_TYPES
    description: str
    link: str | None = None
    notes: str | None = None
    ticket_slug: str | None = None
    version: str | None = None
    row_version: int = pydantic.Field(
        default=1,
        alias='_row_version',
        ge=0,
        lt=2**64,
    )
    is_deleted: bool = False
