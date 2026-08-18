import dataclasses
import datetime
import json
import re
import typing
import warnings

import nanoid
import pydantic
import slugify
from jsonschema_models import models as schema_models

from imbi.common import versioning

__all__ = [
    'Advisory',
    'Blueprint',
    'BlueprintAssignment',
    'BlueprintEdge',
    'BlueprintFilter',
    'Comment',
    'CommentThread',
    'CommitRecord',
    'Component',
    'ComponentIdentifier',
    'ComponentNote',
    'ComponentRelease',
    'ComponentStatus',
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
    'Integration',
    'LinkDefinition',
    'MCPServer',
    'MembershipProperties',
    'Node',
    'OperationLog',
    'Organization',
    'OrganizationEdge',
    'Project',
    'ProjectEnvironmentEdge',
    'ProjectRelationships',
    'ProjectType',
    'PullRequestRecord',
    'RelationshipEdge',
    'RelationshipLink',
    'Release',
    'ReleaseComponentEdge',
    'ReleaseDeploymentEdge',
    'ReleaseLink',
    'Schema',
    'ServiceAccount',
    'Tag',
    'TagFormat',
    'TagRecord',
    'Team',
    'User',
    'effective_component_status',
    'parse_scopes',
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
            'Integration',
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


class TagFormat(pydantic.BaseModel):
    """A named release/deploy tag-format policy.

    ``label`` is the human-facing name shown in the UI (e.g. ``Semver``
    or ``CalVer``); ``pattern`` is a regular expression a tag must match.
    A tag is accepted when it matches *any* configured ``TagFormat`` --
    see ``imbi.common.versioning.matches_tag_formats``.

    Patterns are matched with :func:`re.fullmatch` and validated as
    compilable at assignment time so an invalid expression is rejected at
    the API boundary rather than at deploy/release time.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    label: str = pydantic.Field(min_length=1, max_length=64)
    pattern: str = pydantic.Field(min_length=1, max_length=512)

    @pydantic.field_validator('pattern')
    @classmethod
    def _validate_pattern(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f'Invalid regular expression: {exc}') from exc
        return value


# Convenience constant for seeding the common-case semver policy (e.g.
# ``1.2.3`` / ``v1.2.3``); unconfigured orgs/types impose no restriction.
SEMVER_TAG_FORMAT: typing.Final[TagFormat] = TagFormat(
    label='Semver',
    pattern=versioning.SEMVER_TAG_PATTERN,
)


#: Who may see *which people* read a document, as opposed to how many.
#: Aggregate readership is an operational signal; a named list of who
#: read what and for how long is surveillance-shaped, so it is gated
#: separately from the aggregate and defaults to the narrowest setting
#: that still lets an author learn who reads their own work.
DocumentAnalyticsIdentities = typing.Literal[
    'enabled',  # anyone holding document:analytics:read_identities
    'authors_only',  # that, plus the document's own author
    'disabled',  # nobody; aggregate counts only
]


class Organization(Node):
    tag_formats: list[TagFormat] = []

    document_analytics_identities: DocumentAnalyticsIdentities = 'authors_only'


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
    # ``deployable`` projects deploy into environments (Deployments tab);
    # ``releasable`` projects publish an artifact via tag + release with no
    # deploy step (Releases tab). The two are mutually exclusive: a type is
    # one or the other, or neither.
    deployable: bool = False
    releasable: bool = False
    organization: BelongsToOrganization

    # Overrides the organization's ``tag_formats`` when non-empty (see
    # ``imbi.common.versioning.matches_tag_formats``); empty falls back to
    # the organization policy.
    tag_formats: list[TagFormat] = []

    @pydantic.model_validator(mode='after')
    def validate_deployable_releasable_exclusive(self) -> typing.Self:
        """Reject a type marked both deployable and releasable."""
        if self.deployable and self.releasable:
            raise ValueError(
                'deployable and releasable are mutually exclusive'
            )
        return self


class Integration(Node):
    """A configuration instance of a plugin.

    An Integration is not a generic external-service record — it is one
    configured instance of an installed plugin (identified by
    :attr:`plugin`). One plugin (``github``) backs many Integrations
    (``GitHub.com``, ``GHEC``), each with its own credentials, options,
    and per-capability toggles.

    ``encrypted_credentials`` is the ONLY credential store: a mapping of
    credential field name to its Fernet-encrypted value (see
    :mod:`imbi.common.auth.encryption`). Plaintext must never be assigned;
    callers encrypt before persistence and decrypt on read via
    :func:`imbi.common.plugins.credentials.decrypt_integration_credentials`.
    """

    #: Owning organization. Optional: login-provider Integrations are
    #: global/system-owned (login happens before any org context exists)
    #: and carry no ``BELONGS_TO`` edge; service Integrations set it.
    organization: typing.Annotated[
        Organization | None,
        Edge(rel_type='BELONGS_TO', direction='OUTGOING'),
    ] = None
    team: typing.Annotated[
        Team | None,
        Edge(rel_type='MANAGED_BY', direction='OUTGOING'),
    ] = None
    #: Slug of the installed plugin that backs this Integration.
    plugin: str
    #: Integration-level option values (host, flavor, region, …).
    options: dict[str, typing.Any] = {}
    #: Fernet-encrypted credential blob, keyed by credential field name.
    encrypted_credentials: dict[str, str] = {}
    #: Per-capability state keyed by ``CapabilityKind``:
    #: ``{kind: {'enabled': bool, 'options': {…}}}``.
    capabilities: dict[str, dict[str, typing.Any]] = {}
    # Domain fields carried over from the v2 ThirdPartyService model.
    vendor: str | None = None
    service_url: str | None = None
    category: str | None = None
    status: typing.Literal[
        'active', 'deprecated', 'evaluating', 'inactive'
    ] = 'active'
    links: dict[str, str] = {}
    identifiers: dict[str, int | str] = {}


class IdentityConnection(GraphModel):
    """Per-user, per-Integration identity connection.

    Encrypted-token fields store the *ciphertext* (Fernet via
    :class:`imbi.common.auth.encryption.TokenEncryption`); decryption
    happens in the API repository layer, never on the model.  ``status``
    is one of ``'active' | 'revoked' | 'expired'``.
    """

    integration_id: str
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
    :mod:`imbi.common.auth.encryption`, keyed off
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
    """A free-form, taggable document.

    A document is attached to exactly one owning vertex via an
    ``ATTACHED_TO`` edge — a ``Project``, a ``ProjectType``, or a
    ``User`` (the ``User`` vertex is defined by ``imbi-api``, so only
    the project and project-type edges are typed here).  ``content``
    is markdown and is embedded so future semantic search can surface
    documents alongside other corpus content.

    """

    project: typing.Annotated[
        Project | None,
        Edge(rel_type='ATTACHED_TO', direction='OUTGOING'),
    ] = None
    project_type: typing.Annotated[
        ProjectType | None,
        Edge(rel_type='ATTACHED_TO', direction='OUTGOING'),
    ] = None
    tags: typing.Annotated[
        list[Tag],
        Edge(rel_type='TAGGED_WITH', direction='OUTGOING'),
    ] = []
    title: typing.Annotated[str, Embeddable()]
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
    round-trip through AGE as agtype arrays.  ``body`` is markdown
    text and is embedded so semantic search can surface comments
    alongside other corpus content.

    """

    thread: typing.Annotated[
        CommentThread,
        Edge(rel_type='IN_THREAD', direction='OUTGOING'),
    ]
    author: str
    body: typing.Annotated[
        str,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ]
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
    """Reusable starter content for a ``Document``.

    Templates are scoped to an organization and seed a new document's
    title, content, and tag set. ``type`` declares which attachment
    contexts may use the template: ``'project'`` for project
    documents, ``'user'`` for user documents, ``'project_type'`` for
    project-type documents, and ``'global'`` for every context.
    ``project_type_slugs`` further restricts which project types may
    use the template; an empty list means the template applies to
    every project type in the organization.

    """

    organization: BelongsToOrganization
    type: typing.Literal[
        'project',
        'global',
        'user',
        'project_type',
    ] = 'project'
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


def parse_deployment_events(
    raw: object,
    *,
    on_error: typing.Literal['raise', 'skip'] = 'raise',
) -> list[DeploymentEvent]:
    """Parse the JSON-encoded ``deployments`` edge property.

    A release's ``DEPLOYED_TO`` edge stores its event history as a
    JSON-encoded string (or, once decoded by the graph layer, a list).
    Falsy input and anything that isn't a list yield ``[]``; every list
    entry is validated into a :class:`DeploymentEvent`.

    ``on_error`` controls how malformed data is handled. ``'raise'``
    (the default) lets a JSON decode error or an invalid entry
    propagate, so a bad edge fails loudly. ``'skip'`` is tolerant:
    undecodable JSON yields ``[]`` and each entry that fails validation
    is dropped, keeping the good ones — for callers (e.g. score
    computation) that must not fail the whole operation over one bad
    row.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            data: object = json.loads(raw)
        except json.JSONDecodeError:
            if on_error == 'raise':
                raise
            return []
    else:
        data = raw
    if not isinstance(data, list):
        return []
    events: list[DeploymentEvent] = []
    for entry in typing.cast('list[object]', data):
        try:
            events.append(DeploymentEvent.model_validate(entry))
        except pydantic.ValidationError:
            if on_error == 'raise':
                raise
            continue
    return events


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


#: Governance marks a component (or one of its versions) can carry.
#: The absence of a mark is "current" — it is never stored, so a
#: cleared mark is a removed property rather than a third value.
#: ``forbidden`` is stricter than ``deprecated``; see
#: :func:`effective_component_status`.
ComponentStatus = typing.Literal['deprecated', 'forbidden']

#: Strictest-wins ordering for :func:`effective_component_status`.
_COMPONENT_STATUS_SEVERITY: typing.Final[dict[str, int]] = {
    'deprecated': 1,
    'forbidden': 2,
}


def effective_component_status(
    component_status: str | None,
    release_status: str | None,
) -> ComponentStatus | None:
    """Return the strictest of a component and version status.

    A component marked ``forbidden`` forbids every one of its
    versions, so the component-level mark is inherited by versions
    that carry no mark of their own — and a version may only ever be
    marked *more* strictly than its component, never less. ``None``
    on both sides means current. Unknown values are ignored rather
    than raising, so a hand-edited graph cannot break a report.
    """
    ranked = [
        (_COMPONENT_STATUS_SEVERITY[value], value)
        for value in (component_status, release_status)
        if value in _COMPONENT_STATUS_SEVERITY
    ]
    if not ranked:
        return None
    return typing.cast('ComponentStatus', max(ranked)[1])


class Advisory(GraphModel):
    """A published security advisory affecting component versions.

    One node per ``cve_id`` — the identifier is globally unique and
    MERGEd on, so the same CVE affecting five versions is one node
    with five ``HAS_ADVISORY`` edges rather than five copies. Severity
    is deliberately absent until an OSV/GHSA feed can populate it;
    hand-entered severities go stale silently.
    """

    cve_id: str = pydantic.Field(
        description=(
            'Advisory identifier, upper-cased on the way in '
            '(e.g. CVE-2025-1234 or GHSA-xxxx-xxxx-xxxx).'
        ),
    )
    url: str
    title: str | None = None
    created_by: str


class ComponentNote(GraphModel):
    """An append-only note attached to a ``ComponentRelease``.

    Notes are the governance audit trail: why a version was
    deprecated, what the migration path is, who to ask. They are
    visible to every team — a component is a shared identity, not an
    org-private one — and are never edited or deleted, matching the
    designs. Flat scalar properties only, per the AGE constraint the
    comments model documents.
    """

    author: str
    body: typing.Annotated[
        str,
        Embeddable(chunk=True, mimetype='text/markdown'),
    ]


class Component(GraphModel):
    """A piece of third-party software that may appear as a
    dependency of a project ``Release``.

    Identity is the package URL with version stripped — e.g.
    ``pkg:npm/express`` for any version of express. Versions are
    captured as ``ComponentRelease`` nodes linked via
    ``HAS_RELEASE``.

    A component may be marked ``deprecated`` or ``forbidden`` to steer
    projects off of it wholesale — every version inherits the mark.
    ``status`` is the flag; clearing it removes all three ``status_*``
    properties, mirroring the ``blocked_*`` triple on ``Release``. The
    *why* lives in the notes on the affected versions rather than in a
    reason property, per the report designs.
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
    status: ComponentStatus | None = None
    status_at: datetime.datetime | None = None
    status_by: str | None = None


class ComponentRelease(GraphModel):
    """A specific version of a ``Component``.

    Per-component uniqueness of ``version`` is enforced at the
    application layer via MERGE on
    ``(Component)-[:HAS_RELEASE]->(ComponentRelease {version: ...})``;
    no graph-wide UNIQUE index is possible because two components
    may legitimately ship the same version string.

    ``status`` marks this one version deprecated or forbidden. The
    status a report shows is the strictest of this mark and the
    owning component's — see :func:`effective_component_status`.
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
    advisories: typing.Annotated[
        list[Advisory],
        Edge(rel_type='HAS_ADVISORY', direction='OUTGOING'),
    ] = []
    notes: typing.Annotated[
        list[ComponentNote],
        Edge(rel_type='HAS_NOTE', direction='OUTGOING'),
    ] = []
    status: ComponentStatus | None = None
    status_at: datetime.datetime | None = None
    status_by: str | None = None


class Release(GraphModel):
    """A versioned release of a ``Project``.

    The ``tag`` string is the optional business identity (e.g.
    ``1.0.0`` or ``v2024.05.18``).  Per-project uniqueness is
    enforced at the application layer (two projects may legitimately
    share a tag like ``1.0.0``).  The active tag format is a runtime
    setting — see ``imbi.common.versioning.validate_version``.

    A release may be blocked to keep it from shipping again — e.g. after
    a rollback exposed a regression.  ``blocked_at`` is the flag: when it
    is set, deploys and promotes targeting this release are refused, and
    ``blocked_reason`` explains why.  Unblocking clears all three
    ``blocked_*`` properties.

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
    title: typing.Annotated[str, Embeddable()]
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
    blocked_at: datetime.datetime | None = None
    blocked_by: str | None = None
    blocked_reason: str | None = None


class ReleaseDeploymentEdge(RelationshipEdge):
    """Edge properties for ``Release -[:DEPLOYED_TO]-> Environment``.

    Carries the append-only history of status transitions for the
    release within the target environment.

    """

    deployments: list[DeploymentEvent] = []


class ProjectEnvironmentEdge(RelationshipEdge):
    """Edge properties for ``Project -[:DEPLOYED_IN]-> Environment``.

    ``current_release`` holds the ``id`` of the ``Release`` currently
    deployed to the environment for this project. It is updated by the
    API on every ``success`` deployment event, letting the current
    release per environment be read as a single edge-property lookup
    rather than derived from the ``DEPLOYED_TO`` deployment history.

    ``current_release_at`` is the UTC timestamp of the success event
    that set ``current_release``. The API only advances
    ``current_release`` when an incoming success event is newer than
    this, so out-of-order replays (e.g. a deep resync backfill or a
    delayed webhook) cannot regress the pointer to an older release.

    """

    current_release: str | None = None
    current_release_at: datetime.datetime | None = None


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
    """An Integration event recorded in ClickHouse."""

    id: str = pydantic.Field(default_factory=nanoid.generate)
    project_id: str
    recorded_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    type: str = ''
    integration: str
    attributed_to: str = ''
    metadata: dict[str, typing.Any] = {}
    payload: dict[str, typing.Any] = {}
    version: int = pydantic.Field(default=0, ge=0, lt=2**8)

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
    via :func:`imbi.common.clickhouse.insert`. The table is a
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
    #: Email of the Imbi user the commit author resolves to via identity
    #: attribution (the principal used by ``Release.created_by``); ``''``
    #: when the author maps to no active ``IdentityConnection``.
    author_user: str = ''
    committer_name: str = ''
    #: Rolled-up CI/check state for the commit: ``'pass'`` | ``'fail'`` |
    #: ``'warn'`` | ``'unknown'``. Defaults to ``'unknown'``; providers that
    #: expose check status populate it during sync (see imbi-plugin-github).
    ci_status: typing.Literal['pass', 'fail', 'warn', 'unknown'] = 'unknown'
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

    ``sha`` is always the **commit** the tag resolves to. Providers that
    expose annotated tags as their own objects (git, hence GitHub) must
    peel the tag before recording it: consumers join this column against
    ``commits.sha`` and match it against deployment committishes, so a tag
    object hash silently matches nothing. A tag that cannot be peeled to a
    commit must be skipped rather than recorded against the unresolved
    hash -- no row is better than one nothing can join to.
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


class PullRequestRecord(pydantic.BaseModel):
    """A pull request recorded in the ClickHouse ``pull_requests`` table.

    Written directly by the ``github-pr-sync`` webhook-action plugin --
    both on inbound ``pull_request`` webhook events and during on-demand
    backfill. The table uses ``ReplacingMergeTree(recorded_at)`` keyed by
    ``(project_id, pr_id)``, so re-syncing the same PR is safe.

    ``additions``, ``deletions``, and ``changed_files`` default to ``0``
    for backfill rows because GitHub's list-PRs API omits them; they are
    populated accurately from webhook payloads and individual-PR fetches.
    """

    project_id: str
    pr_id: str
    pr_number: int
    title: str
    url: str
    state: str
    author: str
    draft: bool
    merged: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    merged_at: datetime.datetime | None = None
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    recorded_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )


# Authentication principals. These lived in ``imbi.api.domain.models``
# while imbi-api was the only service that authenticated callers. They
# are here now because three members resolve a bearer token against the
# graph -- api, assistant, and scheduler -- and the shared auth path in
# ``imbi.common.auth.permissions`` needs the principal types. The
# ``imbi.api.domain.models`` names remain as re-exports, so every
# existing ``models.User`` reference resolves to this same class.


class MembershipProperties(pydantic.BaseModel):
    """Properties on User->Organization MEMBER_OF relationships."""

    role: str  # Role slug


class OrganizationEdge(typing.NamedTuple):
    """Edge type for User->Organization MEMBER_OF relationships."""

    node: Organization
    properties: MembershipProperties


class User(GraphModel):
    """User account for authentication and authorization."""

    email: pydantic.EmailStr
    display_name: str
    password_hash: str | None = None
    is_active: bool = True
    is_admin: bool = False
    is_service_account: bool = False
    last_login: datetime.datetime | None = None
    avatar_url: pydantic.HttpUrl | None = None
    email_notifications: bool = True

    organizations: typing.Annotated[
        list[OrganizationEdge],
        Edge(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []


class ServiceAccount(GraphModel):
    """Service account for machine-to-machine authentication."""

    slug: str
    display_name: str
    description: str | None = None
    is_active: bool = True
    last_authenticated: datetime.datetime | None = None
    avatar_url: str | None = None

    organizations: typing.Annotated[
        list[OrganizationEdge],
        Edge(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []


@warnings.deprecated(
    'parse_scopes is a compatibility shim for legacy AGE rows that '
    "stored list properties as PostgreSQL-array strings (e.g. '{a,b}')."
    ' Cypher writes have stored lists as JSON since the list-'
    'serialization fix; callers should switch to ``graph.parse_agtype``'
    ' once every legacy scope row has been rewritten. Plan to remove '
    'this helper alongside that backfill -- see CODE_REVIEW_PUNCHLIST '
    'L4 for the open migration deadline.'
)
def parse_scopes(value: typing.Any) -> list[str]:
    """Convert AGE scope values to a Python list.

    AGE may store list properties as PostgreSQL array strings
    (e.g. ``'{}'`` or ``'{read,write}'``), or as JSON-serialized
    strings (e.g. ``'["read","write"]'``) when they were written
    before the Cypher list-serialization fix.

    """
    if isinstance(value, list):
        return [str(v) for v in typing.cast(list[object], value)]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith('['):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(v) for v in typing.cast(list[object], parsed)]
            except json.JSONDecodeError, ValueError:
                pass
        inner = stripped.strip('{}')
        return inner.split(',') if inner else []
    return []
