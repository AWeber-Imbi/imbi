import dataclasses
import datetime
import json
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
    'Comment',
    'CommentThread',
    'CommitRecord',
    'Component',
    'ComponentIdentifier',
    'ComponentRelease',
    'DeploymentEvent',
    'Document',
    'DocumentTemplate',
    'Edge',
    'Embeddable',
    'Embedding',
    'Environment',
    'Event',
    'GraphModel',
    'IdentityConnection',
    'LinkDefinition',
    'MCPServer',
    'Node',
    'OperationLog',
    'Organization',
    'Plugin',
    'Project',
    'ProjectRelationships',
    'ProjectType',
    'RelationshipEdge',
    'RelationshipLink',
    'Release',
    'ReleaseComponentEdge',
    'ReleaseDeploymentEdge',
    'ReleaseLink',
    'Schema',
    'ServiceApplication',
    'Tag',
    'TagRecord',
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


BelongsToOrganization = typing.Annotated[
    Organization, Edge(rel_type='BELONGS_TO', direction='OUTGOING')
]


class Team(Node):
    organization: BelongsToOrganization


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

    # Surface "Deploy" on the release train when true. Defaults true so
    # existing envs (which were all deployable before this flag landed)
    # keep their direct-deploy affordances without an explicit migration.
    can_deploy: bool = True

    # Surface "Promote" on the release train when true. Opt-in per env
    # so a new env doesn't accidentally accept promotes (which cut tags
    # / create GitHub Releases) before an operator has wired one up.
    can_promote: bool = False

    organization: BelongsToOrganization


class ProjectType(Node):
    deployable: bool = False
    organization: BelongsToOrganization


class ServiceApplication(GraphModel):
    """A registered application for a ThirdPartyService.

    ``encrypted_credentials`` stores per-credential Fernet-encrypted token
    strings (see ``imbi_common.auth.encryption``). Plaintext credentials must
    never be assigned to this field; callers are responsible for encrypting
    values before persistence and decrypting on read.

    """

    slug: str
    name: str
    encrypted_credentials: dict[str, str] = {}


class ThirdPartyService(Node):
    organization: BelongsToOrganization


class Plugin(GraphModel):
    """A plugin instance linked to a ThirdPartyService."""

    plugin_slug: str
    label: str
    options: dict[str, typing.Any] = {}
    api_version: int = 1
    login_capable: bool = False
    used_as_login: bool = False
    connects_users_to: str | None = None
    service: typing.Annotated[
        ThirdPartyService,
        Edge(rel_type='HAS_PLUGIN', direction='INCOMING'),
    ]
    service_application: typing.Annotated[
        ServiceApplication | None,
        Edge(rel_type='USES_APPLICATION', direction='OUTGOING'),
    ] = None


class IdentityConnection(GraphModel):
    """Per-user, per-Plugin identity connection.

    Encrypted-token fields store the *ciphertext* (Fernet via
    :class:`imbi_common.auth.encryption.TokenEncryption`); decryption
    happens in the API repository layer, never on the model.  ``status``
    is one of ``'active' | 'revoked' | 'expired'``.
    """

    plugin_id: str
    user_id: str
    subject: str
    access_token_encrypted: str
    refresh_token_encrypted: str | None = None
    id_token_claims_encrypted: str | None = None
    expires_at: datetime.datetime | None = None
    scopes: list[str] = []
    status: typing.Literal['active', 'revoked', 'expired'] = 'active'
    last_used_at: datetime.datetime | None = None
    metadata: dict[str, typing.Any] = {}


class MCPServer(Node):
    """An external MCP server reachable over streamable HTTP.

    The ``*_encrypted`` fields store the *ciphertext* (Fernet via
    :mod:`imbi_common.auth.encryption`, keyed off
    ``IMBI_CONFIG_ENCRYPTION_KEY``). Plaintext secrets must never be
    assigned to these fields; encryption and decryption happen in the
    repository/consumer layer, never on the model.
    """

    url: pydantic.HttpUrl
    enabled: bool = True
    tool_prefix: str | None = None
    timeout: int = 30
    verify_ssl: bool = True
    ignored_tools: list[str] = []
    auth_type: typing.Literal['none', 'static', 'oauth_client_credentials'] = (
        'none'
    )
    static_header: str | None = None
    static_value_encrypted: str | None = None
    oauth_token_url: pydantic.HttpUrl | None = None
    oauth_client_id: str | None = None
    oauth_client_secret_encrypted: str | None = None
    oauth_scope: str | None = None
    # Runtime health, written by the connection-test endpoint and by the
    # assistant when a tool call against this server fails. ``unknown``
    # means it has never been tested or reported on.
    status: typing.Literal['unknown', 'healthy', 'degraded', 'unreachable'] = (
        'unknown'
    )
    last_tested_at: datetime.datetime | None = None
    last_tested_latency_ms: int | None = pydantic.Field(default=None, ge=0)
    tools_discovered: int | None = pydantic.Field(default=None, ge=0)
    last_error: str | None = None

    @pydantic.field_validator('ignored_tools', mode='before')
    @classmethod
    def _parse_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @pydantic.model_validator(mode='after')
    def _validate_auth_fields(self) -> typing.Self:
        """Require the fields each ``auth_type`` depends on.

        Validates the persisted shape: secret presence is checked via the
        ``*_encrypted`` fields, so this holds equally for a freshly built
        node and for a node assembled by merging a partial update onto an
        existing one.
        """
        if self.auth_type == 'static':
            missing = [
                name
                for name, value in (
                    ('static_header', self.static_header),
                    ('static_value', self.static_value_encrypted),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "auth_type 'static' requires: " + ', '.join(missing)
                )
        elif self.auth_type == 'oauth_client_credentials':
            missing = [
                name
                for name, value in (
                    ('oauth_token_url', self.oauth_token_url),
                    ('oauth_client_id', self.oauth_client_id),
                    (
                        'oauth_client_secret',
                        self.oauth_client_secret_encrypted,
                    ),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "auth_type 'oauth_client_credentials' requires: "
                    + ', '.join(missing)
                )
        return self


class LinkDefinition(Node):
    """Defines available link types for projects in an org.

    Each definition describes one kind of external link
    (e.g. GitHub repository, Grafana dashboard) including
    display metadata and an optional URL template.

    """

    url_template: str | None = None
    organization: BelongsToOrganization


class ProjectRelationships(pydantic.BaseModel):
    """Typed relationship links and counts for a project response.

    Lives in imbi-common (rather than only inside imbi-api) so the
    OpenAPI schema generated for ``ProjectResponse`` matches the runtime
    shape: ``make_response_model`` skips re-injecting ``relationships``
    when the base model already declares it, leaving this typed model
    as the canonical schema.
    """

    team: RelationshipLink
    environments: RelationshipLink
    href: str
    outbound_count: int = 0
    inbound_count: int = 0


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
    score: float | None = None
    # Populated by the API on response build; never read from the graph.
    relationships: ProjectRelationships | None = None

    @pydantic.field_validator('links', 'identifiers', mode='before')
    @classmethod
    def _parse_json_dict(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class Tag(Node):
    organization: BelongsToOrganization


class Document(GraphModel):
    """A free-form, taggable document attached to a ``Project``.

    ``content`` is markdown and is embedded so future semantic search
    can surface documents alongside other corpus content.

    """

    project: typing.Annotated[
        Project,
        Edge(rel_type='ATTACHED_TO', direction='OUTGOING'),
    ]
    tags: typing.Annotated[
        list[Tag],
        Edge(rel_type='TAGGED_WITH', direction='OUTGOING'),
    ] = []
    title: str
    content: typing.Annotated[
        str,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ]
    created_by: str
    updated_by: str | None = None
    is_pinned: bool = False


class CommentThread(GraphModel):
    """A thread of comments anchored to a project ``Document``.

    ``kind`` is ``'page'`` for a whole-document discussion or
    ``'inline'`` for a comment tied to a span of the document's
    text.  The inline anchor is FLATTENED into the four
    ``anchor_*`` scalar properties (rather than a nested model) so
    the stored agtype stays a plain map.  Page-level threads leave
    the anchor fields at their defaults.

    """

    document: typing.Annotated[
        Document,
        Edge(rel_type='ON_DOCUMENT', direction='OUTGOING'),
    ]
    kind: typing.Literal['page', 'inline'] = 'page'
    resolved: bool = False
    resolved_by: str | None = None
    resolved_at: datetime.datetime | None = None
    anchor_quote: str = ''
    anchor_prefix: str = ''
    anchor_suffix: str = ''
    anchor_start: int = 0
    created_by: str


class Comment(GraphModel):
    """A single comment within a ``CommentThread``.

    ``mentions`` and ``acknowledged_by`` hold email addresses and
    round-trip through AGE as agtype arrays.  ``body`` is plain
    markdown text and is intentionally NOT embeddable.

    """

    thread: typing.Annotated[
        CommentThread,
        Edge(rel_type='IN_THREAD', direction='OUTGOING'),
    ]
    author: str
    body: str
    mentions: list[str] = []
    acknowledged_by: list[str] = []
    edited: bool = False

    @pydantic.field_validator(
        'mentions',
        'acknowledged_by',
        mode='before',
    )
    @classmethod
    def _parse_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class DocumentTemplate(Node):
    """Reusable starter content for a project ``Document``.

    Templates are scoped to an organization and seed a new document's
    title, content, and tag set. ``project_type_slugs`` restricts
    which project types may use the template; an empty list means
    the template applies to every project type in the organization.

    """

    organization: BelongsToOrganization
    title: str | None = None
    content: typing.Annotated[
        str,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ] = ''
    tags: typing.Annotated[
        list[Tag],
        Edge(rel_type='TAGGED_WITH', direction='OUTGOING'),
    ] = []
    project_type_slugs: list[str] = []
    sort_order: int = 0


class DeploymentEvent(pydantic.BaseModel):
    """A single status transition for a release deployment.

    A release accumulates a list of these on the ``DEPLOYED_TO``
    edge to a given ``Environment`` — one per status transition.

    """

    timestamp: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    status: typing.Literal[
        'pending',
        'in_progress',
        'success',
        'failed',
        'rolled_back',
    ]
    note: str | None = None
    external_run_id: str | None = None
    external_run_url: str | None = None
    #: Original deployer when observed from a remote (e.g. the GitHub
    #: ``deployment.creator.login`` for resyncs). ``None`` for events
    #: recorded against an in-product action where the operator is
    #: already captured in the ``operations_log`` audit row.
    performed_by: str | None = None


class ReleaseLink(pydantic.BaseModel):
    """A typed external link attached to a ``Release``.

    ``type`` is a free-form discriminator (e.g. ``github_release``
    or ``jira_version``); ``label`` is an optional display string.

    """

    type: str
    url: pydantic.HttpUrl
    label: str | None = None


class ComponentIdentifier(GraphModel):
    """A unique identifier for a software ``Component``.

    Versioned identifier kinds (``purl`` with ``@version``, CPE with
    a version segment) are normalized to their version-agnostic form
    before persistence so a single ``ComponentIdentifier`` resolves
    one ``Component`` regardless of release.  ``(kind, value)`` is
    globally unique.
    """

    kind: typing.Literal['purl', 'cpe', 'bom-ref', 'swid']
    value: str


class Component(GraphModel):
    """A piece of third-party software that may appear as a
    dependency of a project ``Release``.

    Identity is the package URL with version stripped — e.g.
    ``pkg:npm/express`` for any version of express. Versions are
    captured as ``ComponentRelease`` nodes linked via
    ``HAS_RELEASE``.
    """

    purl_name: str = pydantic.Field(
        description=(
            'Canonical package URL with version stripped, used as '
            'the component-identity key (e.g. pkg:npm/express).'
        ),
    )
    name: typing.Annotated[str, Embeddable()]
    ecosystem: str = pydantic.Field(
        description=(
            'Package ecosystem derived from the purl type '
            '(e.g. npm, pypi, maven, golang).'
        ),
    )
    description: typing.Annotated[
        str | None,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ] = None
    identifiers: typing.Annotated[
        list[ComponentIdentifier],
        Edge(rel_type='IDENTIFIED_BY', direction='OUTGOING'),
    ] = []


class ComponentRelease(GraphModel):
    """A specific version of a ``Component``.

    Per-component uniqueness of ``version`` is enforced at the
    application layer via MERGE on
    ``(Component)-[:HAS_RELEASE]->(ComponentRelease {version: ...})``;
    no graph-wide UNIQUE index is possible because two components
    may legitimately ship the same version string.
    """

    component: typing.Annotated[
        Component,
        Edge(rel_type='HAS_RELEASE', direction='INCOMING'),
    ]
    version: str
    license: str | None = None
    supplier: str | None = None
    hashes: dict[str, str] = pydantic.Field(
        default_factory=dict,
        description=(
            'Content-addressable digests keyed by algorithm '
            '(e.g. {"SHA-256": "abc..."}).'
        ),
    )


class Release(GraphModel):
    """A versioned release of a ``Project``.

    The ``tag`` string is the optional business identity (e.g.
    ``1.0.0`` or ``v2024.05.18``).  Per-project uniqueness is
    enforced at the application layer (two projects may legitimately
    share a tag like ``1.0.0``).  The active tag format is a runtime
    setting — see ``imbi_common.versioning.validate_version``.

    """

    project: typing.Annotated[
        Project,
        Edge(rel_type='HAS_RELEASE', direction='INCOMING'),
    ]
    environments: typing.Annotated[
        list[Environment],
        Edge(rel_type='DEPLOYED_TO', direction='OUTGOING'),
    ] = []
    component_releases: typing.Annotated[
        list[ComponentRelease],
        Edge(rel_type='USES_COMPONENT_RELEASE', direction='OUTGOING'),
    ] = []
    tag: str | None = None
    title: str
    description: typing.Annotated[
        str | None,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ] = None
    links: list[ReleaseLink] = []
    created_by: str
    committish: typing.Annotated[
        str,
        pydantic.Field(
            pattern=r'^[0-9a-f]{7}$',
            description=(
                'Short commit SHA (7 lowercase hexadecimal chars) '
                'identifying the source revision for this release.'
            ),
        ),
    ]


class ReleaseDeploymentEdge(RelationshipEdge):
    """Edge properties for ``Release -[:DEPLOYED_TO]-> Environment``.

    Carries the append-only history of status transitions for the
    release within the target environment.

    """

    deployments: list[DeploymentEvent] = []


class ReleaseComponentEdge(RelationshipEdge):
    """Edge properties for
    ``Release -[:USES_COMPONENT_RELEASE]-> ComponentRelease``.

    A given ``ComponentRelease`` may be required by one project's
    release and only used in a dev-group by another's. The
    per-release usage facts therefore live on the edge, not on the
    node:

    * ``scope`` mirrors CycloneDX's ``component.scope``
      (``required`` / ``optional`` / ``excluded``); ``None`` means
      the producer did not declare one.
    * ``groups`` is the list of dependency-group names the producer
      attributed the component to (e.g. ``["dev", "test"]``) — for
      now sourced exclusively from cdxgen's ``cdx:pyproject:group``
      property. The list is alphabetically sorted and de-duplicated
      at ingest time so equality comparisons across releases stay
      stable.
    """

    scope: typing.Literal['required', 'optional', 'excluded'] | None = None
    groups: list[str] = []


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
    plugin_slug: str = ''
    external_run_id: str | None = None


class Event(pydantic.BaseModel):
    """A third-party service event recorded in ClickHouse."""

    id: str = pydantic.Field(default_factory=nanoid.generate)
    project_id: str
    recorded_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    type: str = ''
    third_party_service: str
    attributed_to: str = ''
    metadata: dict[str, typing.Any] = {}
    payload: dict[str, typing.Any] = {}

    @pydantic.field_validator('attributed_to', mode='before')
    @classmethod
    def _coerce_none_to_empty(cls, value: object) -> object:
        """Coerce ``None`` to ``''`` to match the non-Nullable column.

        The events table stores ``attributed_to`` as ``LowCardinality(String)
        DEFAULT ''`` (non-Nullable); inserting ``None`` raises a clickhouse
        DataError. Webhook callers commonly resolve to no attributed user
        (``user_id is None``) and pass that value through directly.
        """
        return '' if value is None else value


class CommitRecord(pydantic.BaseModel):
    """A VCS commit recorded in the ClickHouse ``commits`` table.

    Generic across version-control providers — a GitHub, GitLab, or
    Bitbucket plugin maps its API response onto these fields and inserts
    via :func:`imbi_common.clickhouse.insert`. The table is a
    ``ReplacingMergeTree`` keyed by ``(project_id, sha)``, so re-syncing an
    overlapping commit range collapses duplicates on merge.
    """

    project_id: str
    sha: str
    short_sha: str
    ref: str
    message: str
    author_name: str = ''
    author_email: str = ''
    author_login: str = ''
    committer_name: str = ''
    authored_at: datetime.datetime
    committed_at: datetime.datetime | None = None
    url: str = ''
    pushed_at: datetime.datetime
    recorded_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )


class TagRecord(pydantic.BaseModel):
    """A VCS tag recorded in the ClickHouse ``tags`` table.

    Mirrors :class:`CommitRecord`'s role for tags. The table is a
    ``ReplacingMergeTree`` keyed by ``(project_id, name)``; annotated-tag
    metadata (``message``, ``tagger_*``, ``tagged_at``) is populated when
    the provider exposes it and left at its default otherwise.
    """

    project_id: str
    name: str
    sha: str
    message: str = ''
    tagger_name: str = ''
    tagger_email: str = ''
    tagged_at: datetime.datetime | None = None
    url: str = ''
    recorded_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
