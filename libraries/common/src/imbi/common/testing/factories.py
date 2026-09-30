"""Builders that insert valid rows into the relational test database.

Use them to seed test data, not the endpoints of another domain. Each
builder inserts one row with sensible defaults and returns it as a
``dict`` (all columns, from ``RETURNING *``). A keyword argument sets a
column and replaces its default::

    from imbi.common.testing import databases, factories

    databases.isolated_database()
    with factories.connect() as conn:
        project = factories.project(conn, name='Billing')
        release = factories.release(conn, project_id=project['id'])

A builder makes each missing parent row: ``project(conn)`` makes an
organization, its tenant, and a team. When you give a parent id, the
builder uses the organization of that parent, so a row cannot refer to
a row in another organization. Give ``organization_id`` to put new
parents in an organization that you have.

Values: a ``dict`` becomes JSONB. A ``list`` becomes a PostgreSQL array
(``TEXT[]``); for a ``jsonb_array`` column give
``psycopg.types.json.Jsonb([...])``.

The connection is the superuser connection of
``databases.FACTORY_URL``. It bypasses row-level security, so it can
seed any organization and the shared catalog. Test code only: the
application never uses this connection. Tests of row-level security
must read and write through the ``imbi_app`` connection, not this one.

The file has one section for each Wave 2 agent of the migration. Add
the builders of your tables in your own section only, and register each
one with :func:`builds`. ``tests/test_testing/test_factories.py`` fails
when a table in ``schemata/tables/public/`` has no builder.
"""

import collections.abc
import datetime
import os
import secrets
import typing

import nanoid
import psycopg
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.common.testing import databases

Row = dict[str, typing.Any]
Connection = psycopg.Connection[Row]
Builder = collections.abc.Callable[..., Row]

#: The builder of each table, by table name.
BUILDERS: dict[str, Builder] = {}

_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'
#: The dimension of the text embedding model (schemata README, Known
#: problems 4).
EMBEDDING_DIMENSION = 384
ACTOR = 'factory@example.com'


def connect(url: str | None = None) -> Connection:
    """Open the privileged test connection, in autocommit mode."""
    return psycopg.connect(
        url or os.environ[databases.FACTORY_URL],
        autocommit=True,
        row_factory=rows.dict_row,
    )


def builds[B: Builder](table: str) -> collections.abc.Callable[[B], B]:
    """Register the decorated function as the builder of ``table``."""

    def register(builder: B) -> B:
        if table in BUILDERS:
            raise ValueError(f'{table} already has a builder')
        BUILDERS[table] = builder
        return builder

    return register


def new_id() -> str:
    """Return a new nanoid, the primary key form of the schema."""
    return nanoid.generate()


def unique(prefix: str) -> str:
    """Return ``<prefix>-<random>``, a valid and unique slug."""
    return f'{prefix}-{nanoid.generate(_ALPHABET, 10)}'


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def insert(
    conn: Connection, table: str, values: collections.abc.Mapping[str, object]
) -> Row:
    """Insert one row into ``public.<table>`` and return it."""
    query = sql.SQL(
        'INSERT INTO {table} ({columns}) VALUES ({values}) RETURNING *'
    ).format(
        table=sql.Identifier('public', table),
        columns=sql.SQL(', ').join(map(sql.Identifier, values)),
        values=sql.SQL(', ').join(sql.Placeholder() * len(values)),
    )
    params = [
        pg_json.Jsonb(value) if isinstance(value, dict) else value
        for value in values.values()
    ]
    row = conn.execute(query, params).fetchone()
    if row is None:  # pragma: no cover - INSERT ... RETURNING returns it
        raise RuntimeError(f'the insert into {table} returned no row')
    return row


def get(conn: Connection, table: str, row_id: str) -> Row:
    """Return the row of ``public.<table>`` whose ``id`` is ``row_id``."""
    row = conn.execute(
        sql.SQL('SELECT * FROM {table} WHERE id = %s').format(
            table=sql.Identifier('public', table)
        ),
        [row_id],
    ).fetchone()
    if row is None:
        raise LookupError(f'{table} has no row with the id {row_id}')
    return row


def _organization(
    conn: Connection, values: Row, *parents: tuple[str, str]
) -> str | None:
    """Set ``values['organization_id']`` if it is missing, and return it.

    The value comes from the first parent in ``values``, given as
    ``(column, table)``, or from a new organization. It is ``None`` only
    for the instance sign-in provider and the rows that refer to it.
    """
    if 'organization_id' not in values:
        for column, table in parents:
            if column in values:
                parent = get(conn, table, values[column])
                values['organization_id'] = parent['organization_id']
                break
        else:
            values['organization_id'] = organization(conn)['id']
    organization_id: str | None = values['organization_id']
    return organization_id


def _default(
    values: Row, column: str, make: collections.abc.Callable[[], Row]
) -> None:
    """Set ``values[column]`` to the id of a new row if it is missing."""
    if column not in values:
        values[column] = make()['id']


def _next(
    conn: Connection, table: str, column: str, key: str, value: str
) -> int:
    """Return the next free value of an ordinal column."""
    row = conn.execute(
        sql.SQL(
            'SELECT coalesce(max({column}) + 1, 0) AS next'
            '  FROM {table} WHERE {key} = %s'
        ).format(
            column=sql.Identifier(column),
            table=sql.Identifier('public', table),
            key=sql.Identifier(key),
        ),
        [value],
    ).fetchone()
    return row['next'] if row else 0


# ---------------------------------------------------------------------
# K tenancy: tenants, organizations, teams, environments, project types,
# link definitions, principals, users, service accounts, memberships,
# team members
# ---------------------------------------------------------------------


@builds('tenants')
def tenant(conn: Connection, **values: typing.Any) -> Row:
    slug = unique('tenant')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'tenants', defaults | values)


@builds('organizations')
def organization(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'tenant_id', lambda: tenant(conn))
    slug = unique('org')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'organizations', defaults | values)


@builds('teams')
def team(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('team')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'teams', defaults | values)


@builds('environments')
def environment(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('env')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'environments', defaults | values)


@builds('project_types')
def project_type(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('type')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'project_types', defaults | values)


@builds('link_definitions')
def link_definition(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('link')
    defaults = {
        'id': new_id(),
        'name': slug,
        'slug': slug,
        'url_template': 'https://example.com/{project.slug}',
    }
    return insert(conn, 'link_definitions', defaults | values)


@builds('principals')
def principal(conn: Connection, **values: typing.Any) -> Row:
    """A principal with no user or service account row."""
    defaults = {'id': new_id(), 'principal_type': 'user'}
    return insert(conn, 'principals', defaults | values)


@builds('users')
def user(conn: Connection, **values: typing.Any) -> Row:
    """A user and its principal. A given ``id`` must be a principal."""
    _default(values, 'id', lambda: principal(conn, principal_type='user'))
    handle = unique('user')
    defaults = {'email': f'{handle}@example.com', 'display_name': handle}
    return insert(conn, 'users', defaults | values)


@builds('service_accounts')
def service_account(conn: Connection, **values: typing.Any) -> Row:
    """A service account and its principal."""
    _default(
        values,
        'id',
        lambda: principal(conn, principal_type='service_account'),
    )
    slug = unique('sa')
    defaults = {'slug': slug, 'display_name': slug}
    return insert(conn, 'service_accounts', defaults | values)


@builds('memberships')
def membership(conn: Connection, **values: typing.Any) -> Row:
    """A membership of a new user, with a new role, by default."""
    org = _organization(conn, values, ('role_id', 'roles'))
    _default(values, 'principal_id', lambda: user(conn))
    _default(values, 'role_id', lambda: role(conn, organization_id=org))
    return insert(conn, 'memberships', values)


@builds('team_members')
def team_member(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('team_id', 'teams'))
    _default(values, 'team_id', lambda: team(conn, organization_id=org))
    _default(values, 'user_id', lambda: user(conn))
    return insert(conn, 'team_members', values)


# ---------------------------------------------------------------------
# J tags (the pilot, WP1.7)
# ---------------------------------------------------------------------


@builds('tags')
def tag(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('tag')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'tags', defaults | values)


# ---------------------------------------------------------------------
# L projects: projects and their join tables, blueprints, scoring
# policies
# ---------------------------------------------------------------------


@builds('projects')
def project(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('team_id', 'teams'))
    _default(values, 'team_id', lambda: team(conn, organization_id=org))
    slug = unique('project')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'projects', defaults | values)


@builds('project_type_assignments')
def project_type_assignment(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('project_type_id', 'project_types'),
    )
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    _default(
        values,
        'project_type_id',
        lambda: project_type(conn, organization_id=org),
    )
    return insert(conn, 'project_type_assignments', values)


@builds('project_environments')
def project_environment(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('environment_id', 'environments'),
    )
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    _default(
        values,
        'environment_id',
        lambda: environment(conn, organization_id=org),
    )
    return insert(conn, 'project_environments', values)


@builds('project_dependencies')
def project_dependency(conn: Connection, **values: typing.Any) -> Row:
    """``project_id`` depends on ``dependency_id``."""
    org = _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('dependency_id', 'projects'),
    )
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    _default(
        values, 'dependency_id', lambda: project(conn, organization_id=org)
    )
    return insert(conn, 'project_dependencies', values)


@builds('project_syncs')
def project_sync(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('project_id', 'projects'))
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    return insert(conn, 'project_syncs', {'sync_type': 'commit'} | values)


@builds('project_promotions')
def project_promotion(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('project_id', 'projects'))
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    return insert(conn, 'project_promotions', values)


@builds('blueprints')
def blueprint(conn: Connection, **values: typing.Any) -> Row:
    """A node blueprint for projects, with an empty JSON schema."""
    _organization(conn, values)
    slug = unique('blueprint')
    defaults = {
        'id': new_id(),
        'name': slug,
        'slug': slug,
        'kind': 'node',
        'entity_type': 'Project',
        'json_schema': {'type': 'object', 'properties': {}},
    }
    return insert(conn, 'blueprints', defaults | values)


@builds('scoring_policies')
def scoring_policy(conn: Connection, **values: typing.Any) -> Row:
    """A presence policy on the ``owner`` attribute."""
    _organization(conn, values)
    slug = unique('policy')
    defaults = {
        'id': new_id(),
        'name': slug,
        'slug': slug,
        'category': 'presence',
        'weight': 50,
        'parameters': {'attribute_name': 'owner'},
    }
    return insert(conn, 'scoring_policies', defaults | values)


@builds('scoring_policy_targets')
def scoring_policy_target(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('scoring_policy_id', 'scoring_policies'),
        ('project_type_id', 'project_types'),
    )
    _default(
        values,
        'scoring_policy_id',
        lambda: scoring_policy(conn, organization_id=org),
    )
    _default(
        values,
        'project_type_id',
        lambda: project_type(conn, organization_id=org),
    )
    return insert(conn, 'scoring_policy_targets', values)


# ---------------------------------------------------------------------
# M rbac: roles, permissions, grants, access lists, and credentials
# ---------------------------------------------------------------------


@builds('roles')
def role(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values, ('parent_role_id', 'roles'))
    slug = unique('role')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'roles', defaults | values)


@builds('permissions')
def permission(conn: Connection, **values: typing.Any) -> Row:
    """A permission ``<resource_type>:<action>``; the name follows them."""
    values.setdefault('resource_type', 'project')
    values.setdefault('action', unique('act'))
    values.setdefault('name', f'{values["resource_type"]}:{values["action"]}')
    return insert(conn, 'permissions', values)


@builds('role_grants')
def role_grant(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('role_id', 'roles'))
    _default(values, 'role_id', lambda: role(conn, organization_id=org))
    if 'permission_name' not in values:
        values['permission_name'] = permission(conn)['name']
    return insert(conn, 'role_grants', values)


@builds('resource_acls')
def resource_acl(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    _default(values, 'principal_id', lambda: user(conn))
    defaults = {
        'resource_type': 'project',
        'resource_slug': unique('project'),
        'actions': ['read'],
    }
    return insert(conn, 'resource_acls', defaults | values)


@builds('issued_tokens')
def issued_token(conn: Connection, **values: typing.Any) -> Row:
    """An access token that expires in one hour."""
    _default(values, 'principal_id', lambda: user(conn))
    issued = now()
    defaults = {
        'jti': new_id(),
        'token_type': 'access',
        'issued_at': issued,
        'expires_at': issued + datetime.timedelta(hours=1),
    }
    return insert(conn, 'issued_tokens', defaults | values)


@builds('totp_secrets')
def totp_secret(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'user_id', lambda: user(conn))
    defaults = {'secret_encrypted': secrets.token_urlsafe(16)}
    return insert(conn, 'totp_secrets', defaults | values)


@builds('api_keys')
def api_key(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'principal_id', lambda: user(conn))
    defaults = {
        'id': new_id(),
        'key_id': unique('key'),
        'key_hash': secrets.token_hex(32),
        'name': unique('key'),
    }
    return insert(conn, 'api_keys', defaults | values)


@builds('client_credentials')
def client_credential(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'service_account_id', lambda: service_account(conn))
    defaults = {
        'id': new_id(),
        'client_id': unique('client'),
        'client_secret_hash': secrets.token_hex(32),
        'name': unique('credential'),
    }
    return insert(conn, 'client_credentials', defaults | values)


@builds('oauth_clients')
def oauth_client(conn: Connection, **values: typing.Any) -> Row:
    defaults = {
        'id': new_id(),
        'client_id': unique('client'),
        'redirect_uris': ['https://example.com/callback'],
    }
    return insert(conn, 'oauth_clients', defaults | values)


@builds('identity_connections')
def identity_connection(conn: Connection, **values: typing.Any) -> Row:
    """A connection of a new user to an integration of the organization.

    ``organization_id`` is the organization of the integration: the
    ``check_integration_scope`` trigger requires it.
    """
    org = _organization(conn, values, ('integration_id', 'integrations'))
    _default(
        values,
        'integration_id',
        lambda: integration(conn, organization_id=org),
    )
    _default(values, 'user_id', lambda: user(conn))
    defaults = {'id': new_id(), 'subject': unique('subject')}
    return insert(conn, 'identity_connections', defaults | values)


@builds('password_reset_tokens')
def password_reset_token(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'user_id', lambda: user(conn))
    defaults = {
        'id': new_id(),
        'token_hash': secrets.token_hex(32),
        'expires_at': now() + datetime.timedelta(hours=1),
    }
    return insert(conn, 'password_reset_tokens', defaults | values)


@builds('local_auth_settings')
def local_auth_settings(conn: Connection, **values: typing.Any) -> Row:
    """The one row of the table. It replaces the row that is there."""
    conn.execute('DELETE FROM public.local_auth_settings')
    return insert(conn, 'local_auth_settings', {'enabled': True} | values)


# ---------------------------------------------------------------------
# N releases: releases and blockers
# ---------------------------------------------------------------------


@builds('releases')
def release(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('project_id', 'projects'))
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    tag_name = unique('v1')
    defaults = {
        'id': new_id(),
        'tag': tag_name,
        'committish': secrets.token_hex(20),
        'title': tag_name,
        'created_by': ACTOR,
    }
    return insert(conn, 'releases', defaults | values)


@builds('blockers')
def blocker(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('release_id', 'releases'))
    _default(values, 'release_id', lambda: release(conn, organization_id=org))
    defaults = {
        'id': new_id(),
        'description': 'Blocked by a test',
        'created_by': ACTOR,
    }
    return insert(conn, 'blockers', defaults | values)


# ---------------------------------------------------------------------
# O deployments
# ---------------------------------------------------------------------


@builds('deployments')
def deployment(conn: Connection, **values: typing.Any) -> Row:
    """A successful deployment with no release."""
    org = _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('environment_id', 'environments'),
        ('release_id', 'releases'),
    )
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    _default(
        values,
        'environment_id',
        lambda: environment(conn, organization_id=org),
    )
    defaults = {
        'id': new_id(),
        'deployment_status': 'success',
        'transitioned_at': now(),
    }
    return insert(conn, 'deployments', defaults | values)


# ---------------------------------------------------------------------
# P sbom: the shared catalog and the organization overlays
# ---------------------------------------------------------------------


@builds('components')
def component(conn: Connection, **values: typing.Any) -> Row:
    name = unique('package')
    defaults = {
        'id': new_id(),
        'purl_name': f'pkg:pypi/{name}',
        'name': name,
        'ecosystem': 'pypi',
    }
    return insert(conn, 'components', defaults | values)


@builds('component_releases')
def component_release(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'component_id', lambda: component(conn))
    defaults = {'id': new_id(), 'version': unique('1.0.0')}
    return insert(conn, 'component_releases', defaults | values)


@builds('component_identifiers')
def component_identifier(conn: Connection, **values: typing.Any) -> Row:
    _default(values, 'component_id', lambda: component(conn))
    defaults = {
        'id': new_id(),
        'kind': 'purl',
        'value': f'pkg:pypi/{unique("package")}@1.0.0',
    }
    return insert(conn, 'component_identifiers', defaults | values)


@builds('advisories')
def advisory(conn: Connection, **values: typing.Any) -> Row:
    number = secrets.randbelow(10**7)
    defaults = {'id': new_id(), 'cve_id': f'CVE-2026-{number:07d}'}
    return insert(conn, 'advisories', defaults | values)


@builds('component_governance')
def component_governance(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    _default(values, 'component_id', lambda: component(conn))
    defaults = {'governance_status': 'deprecated', 'status_by': ACTOR}
    return insert(conn, 'component_governance', defaults | values)


@builds('component_release_governance')
def component_release_governance(
    conn: Connection, **values: typing.Any
) -> Row:
    _organization(conn, values)
    _default(values, 'component_release_id', lambda: component_release(conn))
    defaults = {'governance_status': 'deprecated', 'status_by': ACTOR}
    return insert(conn, 'component_release_governance', defaults | values)


@builds('component_notes')
def component_note(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    _default(values, 'component_release_id', lambda: component_release(conn))
    defaults = {'id': new_id(), 'author': ACTOR, 'body': 'A note'}
    return insert(conn, 'component_notes', defaults | values)


@builds('component_advisories')
def component_advisory(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    _default(values, 'component_release_id', lambda: component_release(conn))
    _default(values, 'advisory_id', lambda: advisory(conn))
    defaults = {'url': 'https://example.com/advisory', 'created_by': ACTOR}
    return insert(conn, 'component_advisories', defaults | values)


@builds('component_overrides')
def component_override(conn: Connection, **values: typing.Any) -> Row:
    """An override of the component name."""
    _organization(conn, values)
    _default(values, 'component_id', lambda: component(conn))
    defaults = {'name': unique('override')}
    return insert(conn, 'component_overrides', defaults | values)


@builds('component_release_overrides')
def component_release_override(conn: Connection, **values: typing.Any) -> Row:
    """An override of the release license."""
    _organization(conn, values)
    _default(values, 'component_release_id', lambda: component_release(conn))
    defaults = {'license': 'MIT'}
    return insert(conn, 'component_release_overrides', defaults | values)


# ---------------------------------------------------------------------
# Q documents: documents, templates, comments, uploads
# ---------------------------------------------------------------------


@builds('documents')
def document(conn: Connection, **values: typing.Any) -> Row:
    """A document with no attachment."""
    _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('project_type_id', 'project_types'),
    )
    defaults = {
        'id': new_id(),
        'title': unique('document'),
        'content': '# A document',
        'created_by': ACTOR,
    }
    return insert(conn, 'documents', defaults | values)


@builds('document_tags')
def document_tag(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn, values, ('document_id', 'documents'), ('tag_id', 'tags')
    )
    _default(
        values, 'document_id', lambda: document(conn, organization_id=org)
    )
    _default(values, 'tag_id', lambda: tag(conn, organization_id=org))
    return insert(conn, 'document_tags', values)


@builds('document_likes')
def document_like(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('document_id', 'documents'))
    _default(
        values, 'document_id', lambda: document(conn, organization_id=org)
    )
    _default(values, 'user_id', lambda: user(conn))
    return insert(conn, 'document_likes', values)


@builds('document_templates')
def document_template(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('template')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'document_templates', defaults | values)


@builds('template_project_types')
def template_project_type(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('document_template_id', 'document_templates'),
        ('project_type_id', 'project_types'),
    )
    _default(
        values,
        'document_template_id',
        lambda: document_template(conn, organization_id=org),
    )
    _default(
        values,
        'project_type_id',
        lambda: project_type(conn, organization_id=org),
    )
    return insert(conn, 'template_project_types', values)


@builds('template_tags')
def template_tag(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('document_template_id', 'document_templates'),
        ('tag_id', 'tags'),
    )
    _default(
        values,
        'document_template_id',
        lambda: document_template(conn, organization_id=org),
    )
    _default(values, 'tag_id', lambda: tag(conn, organization_id=org))
    return insert(conn, 'template_tags', values)


@builds('comment_threads')
def comment_thread(conn: Connection, **values: typing.Any) -> Row:
    """A page thread on a new document."""
    org = _organization(conn, values, ('document_id', 'documents'))
    _default(
        values, 'document_id', lambda: document(conn, organization_id=org)
    )
    defaults = {'id': new_id(), 'created_by': ACTOR}
    return insert(conn, 'comment_threads', defaults | values)


@builds('comments')
def comment(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('thread_id', 'comment_threads'))
    _default(
        values, 'thread_id', lambda: comment_thread(conn, organization_id=org)
    )
    defaults = {'id': new_id(), 'author': ACTOR, 'body': 'A comment'}
    return insert(conn, 'comments', defaults | values)


@builds('uploads')
def upload(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    upload_id = new_id()
    defaults = {
        'id': upload_id,
        'filename': 'test.png',
        'content_type': 'image/png',
        'file_size': 1024,
        'storage_key': f'uploads/{upload_id}',
        'uploaded_by': ACTOR,
    }
    return insert(conn, 'uploads', defaults | values)


# ---------------------------------------------------------------------
# R integrations: plugin registrations, integrations, project and
# project type capabilities, webhooks
# ---------------------------------------------------------------------


@builds('plugin_registrations')
def plugin_registration(conn: Connection, **values: typing.Any) -> Row:
    """A registration of an enabled plugin. Its key is ``slug``."""
    defaults = {'slug': unique('plugin'), 'enabled': True}
    return insert(conn, 'plugin_registrations', defaults | values)


@builds('integrations')
def integration(conn: Connection, **values: typing.Any) -> Row:
    """An integration of an organization.

    Give ``organization_id=None`` for the instance sign-in provider.
    """
    _organization(conn, values, ('team_id', 'teams'))
    if 'plugin_slug' not in values:
        values['plugin_slug'] = plugin_registration(conn)['slug']
    slug = unique('integration')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'integrations', defaults | values)


@builds('project_integrations')
def project_integration(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('integration_id', 'integrations'),
    )
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    _default(
        values,
        'integration_id',
        lambda: integration(conn, organization_id=org),
    )
    defaults = {'identifier': unique('identifier')}
    return insert(conn, 'project_integrations', defaults | values)


@builds('project_capabilities')
def project_capability(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('project_id', 'projects'),
        ('integration_id', 'integrations'),
    )
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    _default(
        values,
        'integration_id',
        lambda: integration(conn, organization_id=org),
    )
    defaults = {'capability': 'deployment'}
    return insert(conn, 'project_capabilities', defaults | values)


@builds('project_type_capabilities')
def project_type_capability(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn,
        values,
        ('project_type_id', 'project_types'),
        ('integration_id', 'integrations'),
    )
    _default(
        values,
        'project_type_id',
        lambda: project_type(conn, organization_id=org),
    )
    _default(
        values,
        'integration_id',
        lambda: integration(conn, organization_id=org),
    )
    defaults = {'capability': 'deployment'}
    return insert(conn, 'project_type_capabilities', defaults | values)


@builds('webhooks')
def webhook(conn: Connection, **values: typing.Any) -> Row:
    """A webhook with no integration and no selectors."""
    _organization(conn, values, ('integration_id', 'integrations'))
    slug = unique('webhook')
    defaults = {'id': new_id(), 'name': slug, 'slug': slug}
    return insert(conn, 'webhooks', defaults | values)


@builds('webhook_rules')
def webhook_rule(conn: Connection, **values: typing.Any) -> Row:
    """The next rule of the webhook. It matches every event."""
    org = _organization(conn, values, ('webhook_id', 'webhooks'))
    _default(values, 'webhook_id', lambda: webhook(conn, organization_id=org))
    if 'ordinal' not in values:
        values['ordinal'] = _next(
            conn,
            'webhook_rules',
            'ordinal',
            'webhook_id',
            values['webhook_id'],
        )
    defaults = {'filter_expression': 'true', 'handler': 'github#handle_push'}
    return insert(conn, 'webhook_rules', defaults | values)


# ---------------------------------------------------------------------
# S ai: providers, models, MCP servers, conversations, analysis
# ---------------------------------------------------------------------


@builds('ai_providers')
def ai_provider(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('provider')
    defaults = {
        'id': new_id(),
        'name': slug,
        'slug': slug,
        'driver': 'anthropic',
    }
    return insert(conn, 'ai_providers', defaults | values)


@builds('ai_models')
def ai_model(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(conn, values, ('provider_id', 'ai_providers'))
    _default(
        values, 'provider_id', lambda: ai_provider(conn, organization_id=org)
    )
    slug = unique('model')
    defaults = {
        'id': new_id(),
        'name': slug,
        'slug': slug,
        'provider_model_id': slug,
    }
    return insert(conn, 'ai_models', defaults | values)


@builds('ai_model_teams')
def ai_model_team(conn: Connection, **values: typing.Any) -> Row:
    org = _organization(
        conn, values, ('ai_model_id', 'ai_models'), ('team_id', 'teams')
    )
    _default(
        values, 'ai_model_id', lambda: ai_model(conn, organization_id=org)
    )
    _default(values, 'team_id', lambda: team(conn, organization_id=org))
    return insert(conn, 'ai_model_teams', values)


@builds('mcp_servers')
def mcp_server(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    slug = unique('mcp')
    defaults = {
        'id': new_id(),
        'name': slug,
        'slug': slug,
        'url': 'https://mcp.example.com/mcp',
    }
    return insert(conn, 'mcp_servers', defaults | values)


@builds('conversations')
def conversation(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    _default(values, 'user_id', lambda: user(conn))
    defaults = {'id': new_id(), 'model_name': 'claude-sonnet-5-5'}
    return insert(conn, 'conversations', defaults | values)


@builds('messages')
def message(conn: Connection, **values: typing.Any) -> Row:
    """The next user message of the conversation."""
    org = _organization(conn, values, ('conversation_id', 'conversations'))
    _default(
        values,
        'conversation_id',
        lambda: conversation(conn, organization_id=org),
    )
    if 'message_seq' not in values:
        values['message_seq'] = _next(
            conn,
            'messages',
            'message_seq',
            'conversation_id',
            values['conversation_id'],
        )
    defaults = {'id': new_id(), 'author_role': 'user', 'content': 'Hello'}
    return insert(conn, 'messages', defaults | values)


@builds('analysis_reports')
def analysis_report(conn: Connection, **values: typing.Any) -> Row:
    """The report of a project. A project has at most one."""
    org = _organization(conn, values, ('project_id', 'projects'))
    _default(values, 'project_id', lambda: project(conn, organization_id=org))
    defaults = {'id': new_id(), 'overall_status': 'pass'}
    return insert(conn, 'analysis_reports', defaults | values)


@builds('analysis_results')
def analysis_result(conn: Connection, **values: typing.Any) -> Row:
    """A passed result. ``integration_id`` has no foreign key."""
    org = _organization(conn, values, ('report_id', 'analysis_reports'))
    _default(
        values, 'report_id', lambda: analysis_report(conn, organization_id=org)
    )
    defaults = {
        'slug': unique('check'),
        'title': 'A check',
        'description': 'The check passed.',
        'result_status': 'pass',
        'plugin_slug': 'github',
        'integration_id': new_id(),
    }
    return insert(conn, 'analysis_results', defaults | values)


# ---------------------------------------------------------------------
# T plugins: plugin entities, their keys, and plugin edges
# ---------------------------------------------------------------------


@builds('plugin_entities')
def plugin_entity(conn: Connection, **values: typing.Any) -> Row:
    _organization(conn, values)
    if 'plugin_slug' not in values:
        values['plugin_slug'] = plugin_registration(conn)['slug']
    defaults = {'id': new_id(), 'label': 'AwsAccount'}
    return insert(conn, 'plugin_entities', defaults | values)


@builds('plugin_entity_keys')
def plugin_entity_key(conn: Connection, **values: typing.Any) -> Row:
    """A key of an entity, with the plugin and label of that entity."""
    org = _organization(conn, values, ('entity_id', 'plugin_entities'))
    if 'entity_id' in values:
        entity = get(conn, 'plugin_entities', values['entity_id'])
    else:
        entity = plugin_entity(conn, organization_id=org)
    defaults = {
        'entity_id': entity['id'],
        'plugin_slug': entity['plugin_slug'],
        'label': entity['label'],
        'index_name': unique('index'),
        'key_value': pg_json.Jsonb([unique('key')]),
    }
    return insert(conn, 'plugin_entity_keys', defaults | values)


@builds('plugin_edges')
def plugin_edge(conn: Connection, **values: typing.Any) -> Row:
    """An edge from a new environment to a new plugin entity."""
    org = _organization(conn, values, ('target_id', 'plugin_entities'))
    if 'target_id' in values:
        target = get(conn, 'plugin_entities', values['target_id'])
    else:
        target = plugin_entity(conn, organization_id=org)
    _default(
        values, 'source_id', lambda: environment(conn, organization_id=org)
    )
    defaults = {
        'plugin_slug': target['plugin_slug'],
        'edge_type': 'MAPS_TO',
        'source_label': 'Environment',
        'target_label': target['label'],
        'target_id': target['id'],
    }
    return insert(conn, 'plugin_edges', defaults | values)


# ---------------------------------------------------------------------
# U search: embeddings
# ---------------------------------------------------------------------


@builds('embeddings')
def embedding(conn: Connection, **values: typing.Any) -> Row:
    """A text model chunk of a project description.

    ``node_id`` has no foreign key. Give the id of a real row when the
    test needs one.
    """
    _organization(conn, values)
    vector = ','.join(['0.1'] * EMBEDDING_DIMENSION)
    defaults = {
        'node_label': 'Project',
        'node_id': new_id(),
        'attribute': 'description',
        'chunk_text': 'A chunk',
        'embedding': f'[{vector}]',
    }
    return insert(conn, 'embeddings', defaults | values)
